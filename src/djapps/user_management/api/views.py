import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from config.api.schema import success_response_schema, standard_error_responses
from config.api.responses import StandardizedAPIView, StandardizedResponseMixin, success_response
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from ..models import User
from .permissions import HasAnyGroup, HasPermission, IsAdminOrSuperuser
from .serializers import (
    CurrentUserSerializer,
    LogoutRequestSerializer,
    RegisterSerializer,
    SocialLoginSerializer,
    SocialLoginResponseSerializer,
    StatusResponseSerializer,
    TokenPairSerializer,
    TokenRefreshRequestSerializer,
    TokenRefreshResponseSerializer,
    get_tokens_for_user,
)


def _get_json(url, access_token):
    request = Request(url, headers={"Authorization": f"Bearer {access_token}"})

    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValidationError({"access_token": ["Invalid provider token."]})
        raise ValidationError({"access_token": ["Could not verify provider token."]})
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise ValidationError({"access_token": ["Could not verify provider token."]})


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

    return user


def _social_login_response(user):
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
                    "password": "password123",
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
        request=TokenObtainPairSerializer,
        auth=[],
        examples=[
            OpenApiExample(
                "Login Request",
                value={
                    "email": "editor@example.com",
                    "password": "password123",
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

        profile = _get_json(
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
    serializer_class = SocialLoginSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_social_github",
        summary="Login with GitHub access token",
        description="Verify a GitHub OAuth access token, resolve the user's verified primary email, and return a SmartHub JWT token pair.",
        request=SocialLoginSerializer,
        auth=[],
        examples=[
            OpenApiExample(
                "GitHub Social Login Request",
                value={
                    "access_token": "github_pat_exampletoken",
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
        serializer = SocialLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access_token = serializer.validated_data["access_token"]

        profile = _get_json("https://api.github.com/user", access_token)
        emails = _get_json("https://api.github.com/user/emails", access_token)
        if not isinstance(profile, dict) or not isinstance(emails, list):
            raise ValidationError({"access_token": ["Invalid GitHub profile response."]})

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
                {"access_token": ["GitHub account has no verified primary email."]}
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


class LegacyMeAPIView(MeAPIView):
    @extend_schema(exclude=True)
    def get(self, request):
        return super().get(request)


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
    permission_classes = [HasAnyGroup]
    required_groups = ("editor", "admin")
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="authorization_editor",
        summary="Editor role access check",
        description="Verify access for users in the `editor` or `admin` groups.",
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
    permission_classes = [HasAnyGroup]
    required_groups = ("developer", "admin")
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="authorization_developer",
        summary="Developer role access check",
        description="Verify access for users in the `developer` or `admin` groups.",
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
    required_groups = ("researcher", "admin")
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
    permission_classes = [IsAdminOrSuperuser]
    serializer_class = StatusResponseSerializer

    @extend_schema(
        tags=["Authorization"],
        operation_id="authorization_admin",
        summary="Admin access check",
        description="Verify access for admin or superuser accounts.",
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
