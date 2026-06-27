from django.contrib.auth.models import Group
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from config.api.schema import success_response_schema, standard_error_responses
from config.api.responses import StandardizedAPIView, StandardizedResponseMixin, success_response
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from ..models import User
from .permissions import HasAnyGroup, HasPermission
from ..roles import (
    DATASET_ADMIN_PERMISSIONS,
    DATASET_EDITOR_PERMISSIONS,
    DEVELOPER_API_PERMISSIONS,
    ROLE_RESEARCHER,
    USER_ADMIN_PERMISSIONS,
    sync_user_groups,
)
from .serializers import (
    AdminUserCreateSerializer,
    AdminUserUpdateSerializer,
    ChangePasswordSerializer,
    CurrentUserSerializer,
    EmailTokenObtainPairSerializer,
    EmailVerificationConfirmSerializer,
    EmptyRequestSerializer,
    GroupDetailSerializer,
    GitHubOAuthCodeExchangeSerializer,
    LogoutRequestSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    SocialLoginSerializer,
    SocialLoginResponseSerializer,
    StatusResponseSerializer,
    TokenPairSerializer,
    TokenRefreshRequestSerializer,
    TokenRefreshResponseSerializer,
    UserAdminDetailSerializer,
    UserAdminListSerializer,
    UserGroupAssignmentSerializer,
    get_tokens_for_user,
)
from .accounts import (
    EMAIL_VERIFICATION_PURPOSE,
    PASSWORD_RESET_PURPOSE,
    mark_user_logged_in,
    resolve_user_action_token,
    send_email_verification_email,
    send_password_reset_email,
)
from .social import exchange_github_code_for_access_token, fetch_provider_json
from utils.pagination import CustomPagination
from utils.query import parse_optional_bool


def _get_or_create_social_user(email, first_name="", last_name="", is_verified=True):
    email = User.objects.normalize_email(email).lower()
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "is_verified": is_verified,
        },
    )

    updated_fields = []
    if not user.is_verified and is_verified:
        user.is_verified = True
        updated_fields.append("is_verified")
    if first_name and not user.first_name:
        user.first_name = first_name
        updated_fields.append("first_name")
    if last_name and not user.last_name:
        user.last_name = last_name
        updated_fields.append("last_name")

    if updated_fields:
        user.save(update_fields=updated_fields)

    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])

    from ..roles import ensure_default_user_group

    ensure_default_user_group(user)
    return user


def _social_login_response(user):
    mark_user_logged_in(user)
    return success_response(
        data={
            "user": CurrentUserSerializer(user).data,
            **get_tokens_for_user(user),
        },
        message="Login successful.",
    )


class RegisterAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_register",
        summary="Register a user",
        description="Create a user account with email and password, then return JWT bearer tokens for immediate authenticated use.",
        request=RegisterSerializer,
        auth=[],
        examples=[
            OpenApiExample(
                "Register Request",
                value={
                    "email": "editor@example.com",
                    "password": "StrongPass123!",
                    "first_name": "Data",
                    "last_name": "Editor",
                },
                request_only=True,
            ),
        ],
        responses={
            201: success_response_schema(
                "RegisterSuccessResponse",
                RegisterSerializer,
                description="User created successfully.",
            ),
            **standard_error_responses(
                "Register",
                include_400=True,
            ),
        },
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return success_response(
            data=RegisterSerializer(user).data,
            message="User registered successfully.",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    post=extend_schema(
        tags=["Authentication"],
        operation_id="auth_login",
        summary="Login with email and password",
        description="Exchange valid user credentials for a JWT access token and refresh token. Use the access token as `Authorization: Bearer <access_token>`.",
        request=EmailTokenObtainPairSerializer,
        auth=[],
        examples=[
            OpenApiExample(
                "Login Request",
                value={
                    "email": "editor@example.com",
                    "password": "StrongPass123!",
                },
                request_only=True,
            ),
        ],
        responses={
            200: success_response_schema(
                "LoginSuccessResponse",
                TokenPairSerializer,
                description="JWT token pair issued successfully.",
            ),
            **standard_error_responses(
                "Login",
                include_400=True,
                include_401=True,
            ),
        },
    )
)
class LoginAPIView(StandardizedResponseMixin, TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = EmailTokenObtainPairSerializer
    success_message = "Login successful."


@extend_schema_view(
    post=extend_schema(
        tags=["Authentication"],
        operation_id="auth_refresh",
        summary="Refresh access token",
        description="Exchange a valid refresh token for a new JWT access token.",
        request=TokenRefreshRequestSerializer,
        auth=[],
        examples=[
            OpenApiExample(
                "Refresh Request",
                value={
                    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                },
                request_only=True,
            ),
        ],
        responses={
            200: success_response_schema(
                "RefreshSuccessResponse",
                TokenRefreshResponseSerializer,
                description="New access token issued successfully.",
            ),
            **standard_error_responses(
                "Refresh",
                include_400=True,
                include_401=True,
            ),
        },
    )
)
class RefreshAPIView(StandardizedResponseMixin, TokenRefreshView):
    permission_classes = [AllowAny]
    success_message = "Token refreshed successfully."


class LogoutAPIView(StandardizedAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LogoutRequestSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_logout",
        summary="Logout and blacklist refresh token",
        description="Invalidate the provided refresh token. The access token used to call this endpoint must still be valid.",
        request=LogoutRequestSerializer,
        examples=[
            OpenApiExample(
                "Logout Request",
                value={
                    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                },
                request_only=True,
            ),
        ],
        responses={
            200: success_response_schema(
                "LogoutSuccessResponse",
                description="Refresh token blacklisted successfully.",
            ),
            **standard_error_responses(
                "Logout",
                include_400=True,
                include_401=True,
            ),
        },
    )
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            raise ValidationError({"refresh": ["This field is required."]})

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            raise ValidationError({"refresh": ["Invalid or expired token."]})

        return success_response(message="Logout successful.")


class GoogleSocialLoginAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = SocialLoginSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_social_google",
        summary="Login with Google access token",
        description="Verify a Google OAuth access token, resolve the user profile, and return a SmartHub JWT token pair.",
        request=SocialLoginSerializer,
        auth=[],
        examples=[
            OpenApiExample(
                "Google Social Login Request",
                value={
                    "access_token": "ya29.a0AfH6SMA-example-google-token",
                },
                request_only=True,
            ),
        ],
        responses={
            200: success_response_schema(
                "GoogleSocialLoginSuccessResponse",
                SocialLoginResponseSerializer,
                description="Google account authenticated successfully.",
            ),
            **standard_error_responses(
                "GoogleSocialLogin",
                include_400=True,
            ),
        },
    )
    def post(self, request):
        serializer = SocialLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile = fetch_provider_json(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            serializer.validated_data["access_token"],
        )
        if not isinstance(profile, dict):
            raise ValidationError({"access_token": ["Invalid Google profile response."]})

        email = profile.get("email")
        if not email or not profile.get("email_verified"):
            raise ValidationError(
                {"access_token": ["Google account email is not verified."]}
            )

        user = _get_or_create_social_user(
            email=email,
            first_name=profile.get("given_name", ""),
            last_name=profile.get("family_name", ""),
            is_verified=True,
        )
        return _social_login_response(user)


class GitHubSocialLoginAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = GitHubOAuthCodeExchangeSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_social_github",
        summary="Login with GitHub OAuth authorization code",
        description=(
            "Exchange a GitHub OAuth authorization code for a GitHub user access "
            "token, resolve the user's verified primary email, and return a "
            "SmartHub JWT token pair. The frontend must validate the GitHub "
            "`state` value before calling this endpoint."
        ),
        request=GitHubOAuthCodeExchangeSerializer,
        auth=[],
        examples=[
            OpenApiExample(
                "GitHub Social Login Request",
                value={
                    "code": "github_temporary_authorization_code",
                    "redirect_uri": "http://localhost:3000/auth/github/callback",
                    "code_verifier": "uD5Stn6W2vEx8f3nF0Y6nQKq6C7eB1hW4rT9mLp2aXy",
                },
                request_only=True,
            ),
        ],
        responses={
            200: success_response_schema(
                "GitHubSocialLoginSuccessResponse",
                SocialLoginResponseSerializer,
                description="GitHub account authenticated successfully.",
            ),
            **standard_error_responses(
                "GitHubSocialLogin",
                include_400=True,
            ),
        },
    )
    def post(self, request):
        serializer = GitHubOAuthCodeExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access_token = exchange_github_code_for_access_token(
            code=serializer.validated_data["code"],
            redirect_uri=serializer.validated_data["redirect_uri"],
            code_verifier=serializer.validated_data["code_verifier"],
        )

        profile = fetch_provider_json(
            "https://api.github.com/user",
            access_token,
            error_field="code",
            invalid_message=(
                "GitHub authorization is invalid or missing required scopes."
            ),
            failure_message="Could not verify GitHub authorization.",
        )
        emails = fetch_provider_json(
            "https://api.github.com/user/emails",
            access_token,
            error_field="code",
            invalid_message=(
                "GitHub authorization is invalid or missing required scopes."
            ),
            failure_message="Could not verify GitHub authorization.",
        )
        if not isinstance(profile, dict) or not isinstance(emails, list):
            raise ValidationError({"code": ["Invalid GitHub profile response."]})

        primary_email = next(
            (
                item["email"]
                for item in emails
                if isinstance(item, dict)
                and item.get("primary")
                and item.get("verified")
                and item.get("email")
            ),
            None,
        )
        if not primary_email:
            raise ValidationError(
                {"code": ["GitHub account has no verified primary email."]}
            )

        name_parts = (profile.get("name") or "").split(" ", 1)
        user = _get_or_create_social_user(
            email=primary_email,
            first_name=name_parts[0] if name_parts else "",
            last_name=name_parts[1] if len(name_parts) > 1 else "",
            is_verified=True,
        )
        return _social_login_response(user)


class PublicPingAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="public_ping",
        summary="Public health check",
        description="Confirm that the API is reachable without authentication.",
        auth=[],
        responses={
            200: success_response_schema(
                "PublicPingSuccessResponse",
                StatusResponseSerializer,
                description="API is reachable.",
            ),
        },
    )
    def get(self, request):
        return Response({"status": "ok", "scope": "public"})


class MeAPIView(StandardizedAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CurrentUserSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_me",
        summary="Get current user",
        description="Return the authenticated user's profile, roles, and effective permissions.",
        responses={
            200: success_response_schema(
                "CurrentUserSuccessResponse",
                CurrentUserSerializer,
                description="Current authenticated user.",
            ),
            **standard_error_responses(
                "CurrentUser",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        serializer = CurrentUserSerializer(request.user)
        return Response(serializer.data)

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_me_update",
        summary="Update current user profile",
        description="Update the authenticated user's profile details. Changing the email address marks the account as unverified until email verification is completed again.",
        request=ProfileUpdateSerializer,
        responses={
            200: success_response_schema(
                "CurrentUserUpdateSuccessResponse",
                CurrentUserSerializer,
                description="Current user profile updated successfully.",
            ),
            **standard_error_responses(
                "CurrentUserUpdate",
                include_400=True,
                include_401=True,
            ),
        },
    )
    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return success_response(
            data=CurrentUserSerializer(user).data,
            message="Profile updated successfully.",
        )


class LegacyMeAPIView(MeAPIView):
    @extend_schema(exclude=True)
    def get(self, request):
        return super().get(request)

    @extend_schema(exclude=True)
    def patch(self, request):
        return super().patch(request)


class RegisteredUserAPIView(StandardizedAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="authorization_registered_user",
        summary="Registered user access check",
        description="Simple protected endpoint to verify that a valid JWT bearer token grants access to authenticated users.",
        responses={
            200: success_response_schema(
                "RegisteredUserSuccessResponse",
                StatusResponseSerializer,
            ),
            **standard_error_responses(
                "RegisteredUser",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        return Response({"status": "ok", "scope": "registered user"})


class EditorAPIView(StandardizedAPIView):
    permission_classes = [HasPermission]
    required_permissions = DATASET_EDITOR_PERMISSIONS[1:]
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="authorization_editor",
        summary="Editor permission access check",
        description="Verify access for users granted dataset editor permissions.",
        responses={
            200: success_response_schema(
                "EditorAccessSuccessResponse",
                StatusResponseSerializer,
            ),
            **standard_error_responses(
                "EditorAccess",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        return Response({"status": "ok", "scope": "editor"})


class DeveloperAPIView(StandardizedAPIView):
    permission_classes = [HasPermission]
    required_permissions = DEVELOPER_API_PERMISSIONS
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="authorization_developer",
        summary="Developer permission access check",
        description="Verify access for users granted developer API management permissions.",
        responses={
            200: success_response_schema(
                "DeveloperAccessSuccessResponse",
                StatusResponseSerializer,
            ),
            **standard_error_responses(
                "DeveloperAccess",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        return Response({"status": "ok", "scope": "developer"})


class ResearcherAPIView(StandardizedAPIView):
    permission_classes = [HasAnyGroup]
    required_groups = (ROLE_RESEARCHER, "admin")
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="authorization_researcher",
        summary="Researcher role access check",
        description="Verify access for users in the `researcher` or `admin` groups.",
        responses={
            200: success_response_schema(
                "ResearcherAccessSuccessResponse",
                StatusResponseSerializer,
            ),
            **standard_error_responses(
                "ResearcherAccess",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        return Response({"status": "ok", "scope": "researcher"})


class AdminAPIView(StandardizedAPIView):
    permission_classes = [HasPermission]
    required_permissions = (
        DATASET_ADMIN_PERMISSIONS[1:]
        + USER_ADMIN_PERMISSIONS
    )
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="authorization_admin",
        summary="Admin permission access check",
        description="Verify access for users granted administrative dataset and user-management permissions.",
        responses={
            200: success_response_schema(
                "AdminAccessSuccessResponse",
                StatusResponseSerializer,
            ),
            **standard_error_responses(
                "AdminAccess",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        return Response({"status": "ok", "scope": "admin"})


class PermissionProtectedAPIView(StandardizedAPIView):
    permission_classes = [HasPermission]
    required_permission = "user_management.view_user"
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="authorization_permission_protected",
        summary="Permission-based access check",
        description="Verify access for users granted the `user_management.view_user` permission.",
        responses={
            200: success_response_schema(
                "PermissionProtectedSuccessResponse",
                StatusResponseSerializer,
            ),
            **standard_error_responses(
                "PermissionProtected",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        return Response({"status": "ok", "scope": "permission-protected"})


class PasswordChangeAPIView(StandardizedAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_password_change",
        summary="Change password",
        description="Change the authenticated user's password by providing the current password and a new password.",
        request=ChangePasswordSerializer,
        responses={
            200: success_response_schema(
                "PasswordChangeSuccessResponse",
                description="Password changed successfully.",
            ),
            **standard_error_responses(
                "PasswordChange",
                include_400=True,
                include_401=True,
            ),
        },
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        current_password = serializer.validated_data["current_password"]
        if not request.user.check_password(current_password):
            raise ValidationError({"current_password": ["Current password is incorrect."]})

        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return success_response(message="Password changed successfully.")


class PasswordResetRequestAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordResetRequestSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_password_reset_request",
        summary="Request password reset",
        description="Request a password reset token for the account associated with the provided email address. The response is intentionally the same whether or not the email exists.",
        request=PasswordResetRequestSerializer,
        auth=[],
        responses={
            200: success_response_schema(
                "PasswordResetRequestSuccessResponse",
                description="Password reset request accepted.",
            ),
            **standard_error_responses(
                "PasswordResetRequest",
                include_400=True,
            ),
        },
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(
            email__iexact=serializer.validated_data["email"],
            is_active=True,
        ).first()
        if user is not None:
            send_password_reset_email(user)

        return success_response(
            message="If an account exists for that email, a password reset message has been sent.",
        )


class PasswordResetConfirmAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_password_reset_confirm",
        summary="Confirm password reset",
        description="Complete a password reset by submitting a valid password reset token and a new password.",
        request=PasswordResetConfirmSerializer,
        auth=[],
        responses={
            200: success_response_schema(
                "PasswordResetConfirmSuccessResponse",
                description="Password reset completed successfully.",
            ),
            **standard_error_responses(
                "PasswordResetConfirm",
                include_400=True,
            ),
        },
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = resolve_user_action_token(
            serializer.validated_data["token"],
            PASSWORD_RESET_PURPOSE,
        )
        if not user.is_active:
            raise ValidationError({"token": ["This account is inactive."]})

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return success_response(message="Password reset successfully.")


class EmailVerificationRequestAPIView(StandardizedAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptyRequestSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_email_verification_request",
        summary="Request email verification",
        description="Send an email verification token for the authenticated user's current email address.",
        request=EmptyRequestSerializer,
        responses={
            200: success_response_schema(
                "EmailVerificationRequestSuccessResponse",
                description="Email verification request accepted.",
            ),
            **standard_error_responses(
                "EmailVerificationRequest",
                include_400=True,
                include_401=True,
            ),
        },
    )
    def post(self, request):
        if request.user.is_verified:
            return success_response(message="Email is already verified.")

        send_email_verification_email(request.user)
        return success_response(message="Verification email sent successfully.")


class EmailVerificationConfirmAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = EmailVerificationConfirmSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_email_verification_confirm",
        summary="Confirm email verification",
        description="Verify a user email address using a valid email verification token.",
        request=EmailVerificationConfirmSerializer,
        auth=[],
        responses={
            200: success_response_schema(
                "EmailVerificationConfirmSuccessResponse",
                CurrentUserSerializer,
                description="Email verified successfully.",
            ),
            **standard_error_responses(
                "EmailVerificationConfirm",
                include_400=True,
            ),
        },
    )
    def post(self, request):
        serializer = EmailVerificationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = resolve_user_action_token(
            serializer.validated_data["token"],
            EMAIL_VERIFICATION_PURPOSE,
        )
        if not user.is_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified"])

        return success_response(
            data=CurrentUserSerializer(user).data,
            message="Email verified successfully.",
        )


class UserManagementBaseAPIView(StandardizedAPIView):
    pagination_class = CustomPagination

    def get_base_queryset(self):
        return User.objects.prefetch_related("groups", "user_permissions").order_by("email")

    def get_user(self, user_id):
        return get_object_or_404(self.get_base_queryset(), pk=user_id)

    def paginate_queryset(self, queryset):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        return paginator, page


class UserListAPIView(UserManagementBaseAPIView):
    permission_classes = [HasPermission]
    serializer_class = UserAdminListSerializer
    ordering_choices = {
        "email",
        "-email",
        "created_at",
        "-created_at",
        "last_login",
        "-last_login",
        "last_login_at",
        "-last_login_at",
    }

    @property
    def required_permissions(self):
        if self.request.method == "POST":
            return ("user_management.add_user",)
        return ("user_management.view_user",)

    @extend_schema(
        tags=["Authorization"],
        operation_id="user_admin_list",
        summary="List users",
        description="List users for administration, with pagination and optional filtering by search text, active status, verified status, and group name.",
        responses={
            200: success_response_schema(
                "AdminUserListSuccessResponse",
                description="User list returned successfully.",
            ),
            **standard_error_responses(
                "AdminUserList",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        queryset = self.get_filtered_queryset()
        paginator, page = self.paginate_queryset(queryset)
        serializer = UserAdminListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        tags=["Authorization"],
        operation_id="user_admin_create",
        summary="Create user",
        description="Create a user account from the administration API and optionally assign groups.",
        request=AdminUserCreateSerializer,
        responses={
            201: success_response_schema(
                "AdminUserCreateSuccessResponse",
                UserAdminDetailSerializer,
                description="User created successfully.",
            ),
            **standard_error_responses(
                "AdminUserCreate",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def post(self, request):
        serializer = AdminUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return success_response(
            data=UserAdminDetailSerializer(user).data,
            message="User created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def get_filtered_queryset(self):
        queryset = self.get_base_queryset()
        search = self.request.query_params.get("q")
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        is_active = parse_optional_bool(
            self.request.query_params.get("is_active"),
            "is_active",
        )
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        is_verified = parse_optional_bool(
            self.request.query_params.get("is_verified"),
            "is_verified",
        )
        if is_verified is not None:
            queryset = queryset.filter(is_verified=is_verified)

        group = self.request.query_params.get("group")
        if group:
            queryset = queryset.filter(groups__name=group)

        ordering = self.request.query_params.get("ordering", "email")
        if ordering not in self.ordering_choices:
            raise ValidationError({"ordering": ["Unsupported ordering field."]})

        return queryset.distinct().order_by(ordering)


class UserDetailAPIView(UserManagementBaseAPIView):
    permission_classes = [HasPermission]
    serializer_class = UserAdminDetailSerializer

    @property
    def required_permissions(self):
        if self.request.method == "PATCH":
            return ("user_management.change_user",)
        return ("user_management.view_user",)

    @extend_schema(
        tags=["Authorization"],
        operation_id="user_admin_retrieve",
        summary="Retrieve user",
        description="Retrieve a single user from the administration API.",
        responses={
            200: success_response_schema(
                "AdminUserDetailSuccessResponse",
                UserAdminDetailSerializer,
                description="User retrieved successfully.",
            ),
            **standard_error_responses(
                "AdminUserDetail",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, user_id):
        user = self.get_user(user_id)
        return Response(UserAdminDetailSerializer(user).data)

    @extend_schema(
        tags=["Authorization"],
        operation_id="user_admin_update",
        summary="Update user",
        description="Update basic user attributes from the administration API.",
        request=AdminUserUpdateSerializer,
        responses={
            200: success_response_schema(
                "AdminUserUpdateSuccessResponse",
                UserAdminDetailSerializer,
                description="User updated successfully.",
            ),
            **standard_error_responses(
                "AdminUserUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def patch(self, request, user_id):
        user = self.get_user(user_id)
        serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return success_response(
            data=UserAdminDetailSerializer(user).data,
            message="User updated successfully.",
        )


class UserDeactivateAPIView(UserManagementBaseAPIView):
    permission_classes = [HasPermission]
    required_permission = "user_management.change_user"
    serializer_class = EmptyRequestSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="user_admin_deactivate",
        summary="Deactivate user",
        description="Deactivate a user account without deleting the underlying user record.",
        request=EmptyRequestSerializer,
        responses={
            200: success_response_schema(
                "AdminUserDeactivateSuccessResponse",
                UserAdminDetailSerializer,
                description="User deactivated successfully.",
            ),
            **standard_error_responses(
                "AdminUserDeactivate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, user_id):
        user = self.get_user(user_id)
        if request.user.pk == user.pk:
            raise ValidationError("You cannot deactivate your own account.")

        if not user.is_active:
            return success_response(
                data=UserAdminDetailSerializer(user).data,
                message="User is already inactive.",
            )

        user.is_active = False
        user.save(update_fields=["is_active"])
        return success_response(
            data=UserAdminDetailSerializer(user).data,
            message="User deactivated successfully.",
        )


class UserReactivateAPIView(UserManagementBaseAPIView):
    permission_classes = [HasPermission]
    required_permission = "user_management.change_user"
    serializer_class = EmptyRequestSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="user_admin_reactivate",
        summary="Reactivate user",
        description="Reactivate a previously deactivated user account.",
        request=EmptyRequestSerializer,
        responses={
            200: success_response_schema(
                "AdminUserReactivateSuccessResponse",
                UserAdminDetailSerializer,
                description="User reactivated successfully.",
            ),
            **standard_error_responses(
                "AdminUserReactivate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, user_id):
        user = self.get_user(user_id)
        if user.is_active:
            return success_response(
                data=UserAdminDetailSerializer(user).data,
                message="User is already active.",
            )

        user.is_active = True
        user.save(update_fields=["is_active"])
        return success_response(
            data=UserAdminDetailSerializer(user).data,
            message="User reactivated successfully.",
        )


class UserGroupAssignmentAPIView(UserManagementBaseAPIView):
    permission_classes = [HasPermission]
    required_permission = "user_management.change_user"
    serializer_class = UserGroupAssignmentSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="user_admin_group_assign",
        summary="Assign user groups",
        description="Replace a user's group memberships with the provided group names.",
        request=UserGroupAssignmentSerializer,
        responses={
            200: success_response_schema(
                "AdminUserGroupAssignmentSuccessResponse",
                UserAdminDetailSerializer,
                description="User groups updated successfully.",
            ),
            **standard_error_responses(
                "AdminUserGroupAssignment",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, user_id):
        user = self.get_user(user_id)
        serializer = UserGroupAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sync_user_groups(user, serializer.validated_data["groups"])
        return success_response(
            data=UserAdminDetailSerializer(user).data,
            message="User groups updated successfully.",
        )


class GroupListAPIView(StandardizedAPIView):
    permission_classes = [HasPermission]
    required_permission = "user_management.view_user"
    serializer_class = GroupDetailSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="user_admin_group_list",
        summary="List groups",
        description="List available authorization groups and their assigned permissions.",
        responses={
            200: success_response_schema(
                "AdminGroupListSuccessResponse",
                GroupDetailSerializer(many=True),
                description="Group list returned successfully.",
            ),
            **standard_error_responses(
                "AdminGroupList",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        groups = Group.objects.prefetch_related("permissions").order_by("name")
        return Response(GroupDetailSerializer(groups, many=True).data)
