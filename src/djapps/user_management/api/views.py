from datetime import timedelta

from django.contrib.auth.models import Group
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
)
from config.api.schema import success_response_schema, standard_error_responses
from config.api.responses import StandardizedAPIView, StandardizedResponseMixin, success_response
from djapps.datasets.models import Dataset, DatasetAuditLog, DatasetStatus
from djapps.gateway.models import APIConsumer, APIKey, APIUsageLog
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
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
    AdminActivityEntrySerializer,
    AdminActivityListPayloadSerializer,
    AdminAPICallsSummarySerializer,
    AdminDashboardSummarySerializer,
    AdminDatasetActivitySummarySerializer,
    AdminDownloadsSummarySerializer,
    AdminUserCreateSerializer,
    AdminViewsSummarySerializer,
    CSRFTokenSerializer,
    AdminUserUpdateSerializer,
    ChangePasswordSerializer,
    CurrentUserSerializer,
    EmailTokenObtainPairSerializer,
    EmailVerificationConfirmSerializer,
    EmptyRequestSerializer,
    GroupDetailSerializer,
    GitHubOAuthCodeExchangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    SocialLoginSerializer,
    SocialLoginResponseSerializer,
    StatusResponseSerializer,
    TokenPairSerializer,
    TokenRefreshResponseSerializer,
    UserAdminDetailSerializer,
    UserAdminListSerializer,
    UserGroupAssignmentSerializer,
    VersionedTokenRefreshSerializer,
    get_tokens_for_user,
)
from .auth_cookies import (
    clear_auth_token_cookies,
    get_refresh_token_from_request,
    set_auth_token_cookies,
)
from .csrf import build_csrf_response_data, enforce_request_csrf, issue_csrf_token
from .accounts import (
    EMAIL_VERIFICATION_PURPOSE,
    PASSWORD_RESET_PURPOSE,
    invalidate_user_tokens,
    mark_user_logged_in,
    resolve_user_action_token,
    send_email_verification_email,
    send_password_reset_email,
)
from .social import exchange_github_code_for_access_token, fetch_provider_json
from utils.pagination import CustomPagination
from utils.query import parse_optional_bool


ADMIN_REQUIRED_PERMISSIONS = DATASET_ADMIN_PERMISSIONS[1:] + USER_ADMIN_PERMISSIONS
ADMIN_ANALYTICS_PERMISSIONS = ADMIN_REQUIRED_PERMISSIONS + (
    "gateway.view_apiconsumer",
    "gateway.view_apikey",
    "gateway.view_apiusagelog",
)
DEFAULT_ADMIN_ANALYTICS_DAYS = 30
MAX_ADMIN_ANALYTICS_DAYS = 365
ADMIN_ANALYTICS_TOP_LIMIT = 5
DATASET_VIEW_ACTIONS = (
    "file_previewed",
    "file_data_accessed",
    "file_schema_accessed",
)
DATASET_RECORD_ACTIONS = (
    "dataset_created",
    "dataset_updated",
    "dataset_deleted",
    "dataset_restored",
    "dataset_owner_transferred",
)
DATASET_WORKFLOW_ACTIONS = (
    "dataset_review_submitted",
    "dataset_review_approved",
    "dataset_review_rejected",
    "dataset_published",
    "dataset_unpublished",
)
DATASET_ACTIVITY_EXCLUDED_ACTIONS = DATASET_VIEW_ACTIONS + ("file_downloaded",)
ADMIN_ANALYTICS_DAYS_PARAMETER = OpenApiParameter(
    name="days",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description=(
        "Trailing calendar days to include in the aggregation. "
        f"Minimum 1, maximum {MAX_ADMIN_ANALYTICS_DAYS}. Defaults to "
        f"{DEFAULT_ADMIN_ANALYTICS_DAYS}."
    ),
)


def _compact_activity_details(details):
    return {
        key: value
        for key, value in (details or {}).items()
        if value is not None and value != ""
    }


def _parse_analytics_days(request):
    raw_days = request.query_params.get("days")
    if raw_days in (None, ""):
        return DEFAULT_ADMIN_ANALYTICS_DAYS

    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        raise ValidationError({"days": ["Enter a whole number."]})

    if not 1 <= days <= MAX_ADMIN_ANALYTICS_DAYS:
        raise ValidationError(
            {
                "days": [
                    f"Ensure this value is between 1 and {MAX_ADMIN_ANALYTICS_DAYS}."
                ]
            }
        )
    return days


def _get_analytics_start_date(days):
    return timezone.localdate() - timedelta(days=days - 1)


def _fill_daily_series(rows, start_date, days, default_values):
    rows_by_date = {row["date"]: row for row in rows}
    series = []
    for offset in range(days):
        current_date = start_date + timedelta(days=offset)
        row = {"date": current_date, **default_values}
        if current_date in rows_by_date:
            row.update(
                {
                    key: value
                    for key, value in rows_by_date[current_date].items()
                    if key != "date"
                }
            )
        series.append(row)
    return series


def _serialize_top_dataset_counts(rows):
    return [
        {
            "dataset_id": str(row["dataset_id"]),
            "dataset_slug": row.get("dataset__slug"),
            "count": row["count"],
        }
        for row in rows
        if row.get("dataset_id")
    ]


def _serialize_dataset_activity(log):
    return {
        "id": str(log.id),
        "activity_type": "dataset_audit",
        "action": log.action,
        "created_at": log.created_at,
        "actor_email": getattr(log.actor, "email", None),
        "dataset_id": str(log.dataset_id) if log.dataset_id else None,
        "dataset_slug": getattr(log.dataset, "slug", None),
        "target_model": log.target_model,
        "target_id": str(log.target_id) if log.target_id else None,
        "endpoint": None,
        "method": None,
        "status_code": None,
        "summary": f"{log.action} on {log.dataset.slug}",
        "details": log.details or {},
    }


def _serialize_api_usage_activity(log, dataset_slug_map):
    actor_email = None
    if log.consumer_id and log.consumer is not None and getattr(log.consumer, "user", None):
        actor_email = log.consumer.user.email

    return {
        "id": str(log.id),
        "activity_type": "api_usage",
        "action": "api_request",
        "created_at": log.created_at,
        "actor_email": actor_email,
        "dataset_id": str(log.dataset_id) if log.dataset_id else None,
        "dataset_slug": dataset_slug_map.get(log.dataset_id),
        "target_model": "gateway.apiusagelog",
        "target_id": str(log.id),
        "endpoint": log.endpoint,
        "method": log.method,
        "status_code": log.status_code,
        "summary": f"{log.method} {log.endpoint} ({log.status_code})",
        "details": _compact_activity_details(
            {
                "consumer_name": getattr(log.consumer, "name", None),
                "api_key_name": getattr(log.api_key, "name", None),
                "api_key_prefix": getattr(log.api_key, "prefix", None),
                "response_time_ms": log.response_time_ms,
                "error_code": log.error_code,
                "ip_address": log.ip_address,
            }
        ),
    }


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


def _social_login_response(request, user):
    mark_user_logged_in(user)
    tokens = get_tokens_for_user(user)
    issue_csrf_token(request, rotate=True)
    response = success_response(
        data={
            "user": CurrentUserSerializer(user).data,
            "access": tokens["access"],
        },
        message="Login successful.",
    )
    set_auth_token_cookies(
        response,
        access_token=tokens["access"],
        refresh_token=tokens["refresh"],
    )
    return response


class CSRFCookieAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = CSRFTokenSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_csrf",
        summary="Issue CSRF token",
        description=(
            "Create or refresh the CSRF cookie required for browser-based, "
            "credentialed authentication requests. The frontend should call "
            "this endpoint first, then send the returned token in the "
            "`X-CSRFToken` header on login, register, refresh, social login, "
            "logout, and other cookie-authenticated mutating requests."
        ),
        auth=[],
        responses={
            200: success_response_schema(
                "CSRFCookieSuccessResponse",
                CSRFTokenSerializer,
                description="CSRF token issued successfully.",
            ),
        },
    )
    def get(self, request):
        return success_response(
            data=build_csrf_response_data(request),
            message="CSRF token issued successfully.",
        )


class RegisterAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_register",
        summary="Register a user",
        description=(
            "Create a user account with email and password, return a JWT "
            "access token in the response body, and set both access and "
            "refresh tokens in HttpOnly cookies. Browser clients must send "
            "a valid CSRF token."
        ),
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
                include_403=True,
            ),
        },
    )
    def post(self, request):
        enforce_request_csrf(request)
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        issue_csrf_token(request, rotate=True)
        response = success_response(
            data=RegisterSerializer(user).data,
            message="User registered successfully.",
            status_code=status.HTTP_201_CREATED,
        )
        set_auth_token_cookies(
            response,
            access_token=user.access,
            refresh_token=user.refresh_token,
        )
        return response


@extend_schema_view(
    post=extend_schema(
        tags=["Authentication"],
        operation_id="auth_login",
        summary="Login with email and password",
        description=(
            "Exchange valid user credentials for a JWT access token. The "
            "access and refresh tokens are set in HttpOnly cookies. Clients "
            "may also use the returned access token as "
            "`Authorization: Bearer <access_token>`. Browser clients must "
            "send a valid CSRF token."
        ),
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
                description="JWT access token issued successfully.",
            ),
            **standard_error_responses(
                "Login",
                include_400=True,
                include_403=True,
                include_401=True,
            ),
        },
    )
)
class LoginAPIView(StandardizedResponseMixin, TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = EmailTokenObtainPairSerializer
    success_message = "Login successful."

    def post(self, request, *args, **kwargs):
        enforce_request_csrf(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issue_csrf_token(request, rotate=True)
        response = success_response(
            data={"access": serializer.validated_data["access"]},
            message=self.success_message,
        )
        set_auth_token_cookies(
            response,
            access_token=serializer.validated_data["access"],
            refresh_token=serializer.validated_data["refresh"],
        )
        return response


@extend_schema_view(
    post=extend_schema(
        tags=["Authentication"],
        operation_id="auth_refresh",
        summary="Refresh access token",
        description=(
            "Exchange the refresh token stored in the HttpOnly cookie for a "
            "new JWT access token. The access-token cookie is updated on every "
            "refresh. If refresh token rotation is enabled, the refresh cookie "
            "is updated as well. Browser clients must send a valid CSRF token."
        ),
        request=EmptyRequestSerializer,
        auth=[],
        responses={
            200: success_response_schema(
                "RefreshSuccessResponse",
                TokenRefreshResponseSerializer,
                description="New access token issued successfully.",
            ),
            **standard_error_responses(
                "Refresh",
                include_400=True,
                include_403=True,
                include_401=True,
            ),
        },
    )
)
class RefreshAPIView(StandardizedResponseMixin, TokenRefreshView):
    permission_classes = [AllowAny]
    serializer_class = VersionedTokenRefreshSerializer
    success_message = "Token refreshed successfully."

    def post(self, request, *args, **kwargs):
        enforce_request_csrf(request)
        refresh_token = get_refresh_token_from_request(request)
        serializer = self.get_serializer(data={"refresh": refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc
        issue_csrf_token(request)
        response = success_response(
            data={"access": serializer.validated_data["access"]},
            message=self.success_message,
        )
        set_auth_token_cookies(
            response,
            access_token=serializer.validated_data["access"],
            refresh_token=serializer.validated_data.get("refresh"),
        )
        return response


class LogoutAPIView(StandardizedAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptyRequestSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_logout",
        summary="Logout and blacklist refresh token",
        description=(
            "Invalidate the refresh token stored in the HttpOnly cookie and "
            "clear both authentication cookies from the client. The access "
            "token used to call this endpoint must still be valid. Browser "
            "clients must send a valid CSRF token."
        ),
        request=EmptyRequestSerializer,
        responses={
            200: success_response_schema(
                "LogoutSuccessResponse",
                description="Logout completed successfully.",
            ),
            **standard_error_responses(
                "Logout",
                include_403=True,
                include_401=True,
            ),
        },
    )
    def post(self, request):
        enforce_request_csrf(request)
        refresh_token = get_refresh_token_from_request(request, required=False)
        issue_csrf_token(request, rotate=True)
        response = success_response(message="Logout successful.")
        clear_auth_token_cookies(response)

        if not refresh_token:
            return response

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return response

        return response


class GoogleSocialLoginAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = SocialLoginSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_social_google",
        summary="Login with Google access token",
        description=(
            "Verify a Google OAuth access token, resolve the user profile, "
            "return a SmartHub JWT access token in the response body, and set "
            "access and refresh tokens in HttpOnly cookies. Browser clients "
            "must send a valid CSRF token."
        ),
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
                include_403=True,
            ),
        },
    )
    def post(self, request):
        enforce_request_csrf(request)
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
        return _social_login_response(request, user)


class GitHubSocialLoginAPIView(StandardizedAPIView):
    permission_classes = [AllowAny]
    serializer_class = GitHubOAuthCodeExchangeSerializer

    @extend_schema(
        tags=["Authentication"],
        operation_id="auth_social_github",
        summary="Login with GitHub OAuth authorization code",
        description=(
            "Exchange a GitHub OAuth authorization code for a GitHub user access "
            "token, resolve the user's verified primary email, return a "
            "SmartHub JWT access token in the response body, and set access "
            "and refresh tokens in HttpOnly cookies. The frontend must "
            "validate the GitHub `state` value before calling this endpoint. "
            "Browser clients must send a valid CSRF token."
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
                include_403=True,
            ),
        },
    )
    def post(self, request):
        enforce_request_csrf(request)
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
        return _social_login_response(request, user)


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
        description=(
            "Return the authenticated user's profile, roles, and effective "
            "permissions. Authentication may be supplied by bearer token or "
            "access-token cookie."
        ),
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
        description=(
            "Update the authenticated user's profile details. Changing the "
            "email address marks the account as unverified until email "
            "verification is completed again."
        ),
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
        description=(
            "Simple protected endpoint to verify that a valid bearer token or "
            "access-token cookie grants access to authenticated users."
        ),
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
    required_permissions = ADMIN_REQUIRED_PERMISSIONS
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


class AdminAnalyticsBaseAPIView(StandardizedAPIView):
    permission_classes = [HasPermission]
    required_permissions = ADMIN_ANALYTICS_PERMISSIONS
    pagination_class = CustomPagination

    def paginate_queryset(self, queryset):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        return paginator, page

    def get_analytics_window(self):
        days = _parse_analytics_days(self.request)
        return days, _get_analytics_start_date(days)


class AdminActivityAPIView(AdminAnalyticsBaseAPIView):
    serializer_class = AdminActivityEntrySerializer

    @extend_schema(
        tags=["Administration"],
        operation_id="admin_activity_list",
        summary="List admin activity",
        description=(
            "Return recent administrative activity across dataset audit logs and "
            "gateway API usage logs."
        ),
        parameters=[
            OpenApiParameter(
                name="type",
                type=OpenApiTypes.STR,
                enum=["dataset_audit", "api_usage"],
                location=OpenApiParameter.QUERY,
                description="Filter activity by source type.",
            ),
            OpenApiParameter(
                name="page",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Page number.",
            ),
            OpenApiParameter(
                name="page_size",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Number of items per page. Maximum 100.",
            ),
        ],
        responses={
            200: success_response_schema(
                "AdminActivityListSuccessResponse",
                AdminActivityListPayloadSerializer,
                description="Admin activity returned successfully.",
            ),
            **standard_error_responses(
                "AdminActivityList",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        activity_type = request.query_params.get("type")
        if activity_type and activity_type not in {"dataset_audit", "api_usage"}:
            raise ValidationError(
                {"type": ["Supported values are dataset_audit and api_usage."]}
            )

        entries = []
        if activity_type in {None, "dataset_audit"}:
            dataset_logs = DatasetAuditLog.objects.select_related(
                "dataset",
                "actor",
            ).order_by("-created_at", "-id")
            entries.extend(_serialize_dataset_activity(log) for log in dataset_logs)

        if activity_type in {None, "api_usage"}:
            usage_logs = list(
                APIUsageLog.objects.select_related(
                    "api_key",
                    "consumer__user",
                ).order_by("-created_at", "-id")
            )
            dataset_slug_map = {
                dataset.id: dataset.slug
                for dataset in Dataset.all_objects.filter(
                    id__in={log.dataset_id for log in usage_logs if log.dataset_id}
                )
            }
            entries.extend(
                _serialize_api_usage_activity(log, dataset_slug_map)
                for log in usage_logs
            )

        entries.sort(
            key=lambda item: (item["created_at"], item["id"]),
            reverse=True,
        )
        paginator, page = self.paginate_queryset(entries)
        serializer = self.serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminDashboardSummaryAPIView(AdminAnalyticsBaseAPIView):
    serializer_class = AdminDashboardSummarySerializer

    @extend_schema(
        tags=["Administration"],
        operation_id="admin_dashboard_summary",
        summary="Get admin dashboard summary",
        description=(
            "Return high-level administration counts for users, datasets, "
            "API consumers, API keys, and recent platform activity."
        ),
        responses={
            200: success_response_schema(
                "AdminDashboardSummarySuccessResponse",
                AdminDashboardSummarySerializer,
                description="Admin dashboard summary returned successfully.",
            ),
            **standard_error_responses(
                "AdminDashboardSummary",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        last_24h = timezone.now() - timedelta(hours=24)

        user_summary = User.objects.aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(is_active=True)),
            inactive=Count("id", filter=Q(is_active=False)),
            verified=Count("id", filter=Q(is_verified=True)),
            staff=Count("id", filter=Q(is_staff=True)),
            superusers=Count("id", filter=Q(is_superuser=True)),
        )

        active_datasets = Dataset.objects
        dataset_summary = {
            "total": Dataset.all_objects.count(),
            "active": active_datasets.count(),
            "deleted": Dataset.all_objects.filter(deleted_at__isnull=False).count(),
            "draft": active_datasets.filter(status=DatasetStatus.DRAFT).count(),
            "in_review": active_datasets.filter(status=DatasetStatus.IN_REVIEW).count(),
            "approved": active_datasets.filter(status=DatasetStatus.APPROVED).count(),
            "rejected": active_datasets.filter(status=DatasetStatus.REJECTED).count(),
            "published": active_datasets.filter(status=DatasetStatus.PUBLISHED).count(),
        }

        api_summary = {
            "consumers_total": APIConsumer.objects.count(),
            "consumers_active": APIConsumer.objects.filter(status="active").count(),
            "api_keys_total": APIKey.objects.count(),
            "api_keys_active": APIKey.objects.filter(status="active").count(),
            "api_keys_revoked": APIKey.objects.filter(status="revoked").count(),
            "api_keys_expired": APIKey.objects.filter(status="expired").count(),
            "requests_total": APIUsageLog.objects.count(),
            "requests_last_24h": APIUsageLog.objects.filter(created_at__gte=last_24h).count(),
            "error_requests_last_24h": APIUsageLog.objects.filter(
                created_at__gte=last_24h,
                status_code__gte=400,
            ).count(),
        }

        activity_summary = {
            "dataset_audit_logs_total": DatasetAuditLog.objects.count(),
            "api_usage_logs_total": APIUsageLog.objects.count(),
            "last_24h_total": (
                DatasetAuditLog.objects.filter(created_at__gte=last_24h).count()
                + APIUsageLog.objects.filter(created_at__gte=last_24h).count()
            ),
        }

        serializer = self.serializer_class(
            {
                "users": user_summary,
                "datasets": dataset_summary,
                "api": api_summary,
                "activity": activity_summary,
            }
        )
        return success_response(data=serializer.data)


class AdminDashboardAPICallsSummaryAPIView(AdminAnalyticsBaseAPIView):
    serializer_class = AdminAPICallsSummarySerializer

    @extend_schema(
        tags=["Administration"],
        operation_id="admin_dashboard_api_calls_summary",
        summary="Get admin API call aggregation",
        description=(
            "Return aggregated API call metrics for the requested trailing day window, "
            "including daily totals and top endpoints."
        ),
        parameters=[ADMIN_ANALYTICS_DAYS_PARAMETER],
        responses={
            200: success_response_schema(
                "AdminDashboardAPICallsSummarySuccessResponse",
                AdminAPICallsSummarySerializer,
                description="Admin API call aggregation returned successfully.",
            ),
            **standard_error_responses(
                "AdminDashboardAPICallsSummary",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        days, start_date = self.get_analytics_window()
        queryset = APIUsageLog.objects.filter(created_at__date__gte=start_date)

        totals = queryset.aggregate(
            total_requests=Count("id"),
            success_requests=Count("id", filter=Q(status_code__lt=400)),
            error_requests=Count("id", filter=Q(status_code__gte=400)),
            unique_consumers=Count("consumer_id", distinct=True),
            unique_api_keys=Count("api_key_id", distinct=True),
            average_response_time_ms=Avg("response_time_ms"),
        )
        if totals["average_response_time_ms"] is not None:
            totals["average_response_time_ms"] = float(
                round(totals["average_response_time_ms"], 2)
            )

        by_day_rows = list(
            queryset.annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(
                total_requests=Count("id"),
                success_requests=Count("id", filter=Q(status_code__lt=400)),
                error_requests=Count("id", filter=Q(status_code__gte=400)),
            )
            .order_by("date")
        )
        top_endpoints = list(
            queryset.values("endpoint", "method")
            .annotate(
                request_count=Count("id"),
                error_count=Count("id", filter=Q(status_code__gte=400)),
            )
            .order_by("-request_count", "endpoint", "method")[:ADMIN_ANALYTICS_TOP_LIMIT]
        )

        serializer = self.serializer_class(
            {
                "days": days,
                "totals": totals,
                "by_day": _fill_daily_series(
                    by_day_rows,
                    start_date,
                    days,
                    {
                        "total_requests": 0,
                        "success_requests": 0,
                        "error_requests": 0,
                    },
                ),
                "top_endpoints": top_endpoints,
            }
        )
        return success_response(data=serializer.data)


class AdminDashboardDownloadsSummaryAPIView(AdminAnalyticsBaseAPIView):
    serializer_class = AdminDownloadsSummarySerializer

    @extend_schema(
        tags=["Administration"],
        operation_id="admin_dashboard_downloads_summary",
        summary="Get admin download aggregation",
        description=(
            "Return aggregated dataset download metrics for the requested trailing day window."
        ),
        parameters=[ADMIN_ANALYTICS_DAYS_PARAMETER],
        responses={
            200: success_response_schema(
                "AdminDashboardDownloadsSummarySuccessResponse",
                AdminDownloadsSummarySerializer,
                description="Admin download aggregation returned successfully.",
            ),
            **standard_error_responses(
                "AdminDashboardDownloadsSummary",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        days, start_date = self.get_analytics_window()
        queryset = DatasetAuditLog.objects.select_related("dataset").filter(
            created_at__date__gte=start_date,
            action="file_downloaded",
        )

        totals = {
            "total_downloads": queryset.count(),
            "unique_datasets": queryset.values("dataset_id").distinct().count(),
            "unique_files": queryset.exclude(target_id__isnull=True)
            .values("target_id")
            .distinct()
            .count(),
            "authenticated_downloads": queryset.filter(actor__isnull=False).count(),
            "anonymous_downloads": queryset.filter(actor__isnull=True).count(),
        }
        by_day_rows = list(
            queryset.annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(total_downloads=Count("id"))
            .order_by("date")
        )
        top_datasets = _serialize_top_dataset_counts(
            list(
                queryset.values("dataset_id", "dataset__slug")
                .annotate(count=Count("id"))
                .order_by("-count", "dataset__slug")[:ADMIN_ANALYTICS_TOP_LIMIT]
            )
        )

        serializer = self.serializer_class(
            {
                "days": days,
                "totals": totals,
                "by_day": _fill_daily_series(
                    by_day_rows,
                    start_date,
                    days,
                    {"total_downloads": 0},
                ),
                "top_datasets": top_datasets,
            }
        )
        return success_response(data=serializer.data)


class AdminDashboardViewsSummaryAPIView(AdminAnalyticsBaseAPIView):
    serializer_class = AdminViewsSummarySerializer

    @extend_schema(
        tags=["Administration"],
        operation_id="admin_dashboard_views_summary",
        summary="Get admin dataset view aggregation",
        description=(
            "Return aggregated dataset view metrics for the requested trailing day window. "
            "Views are derived from preview, structured data, and schema access audit events."
        ),
        parameters=[ADMIN_ANALYTICS_DAYS_PARAMETER],
        responses={
            200: success_response_schema(
                "AdminDashboardViewsSummarySuccessResponse",
                AdminViewsSummarySerializer,
                description="Admin dataset view aggregation returned successfully.",
            ),
            **standard_error_responses(
                "AdminDashboardViewsSummary",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        days, start_date = self.get_analytics_window()
        queryset = DatasetAuditLog.objects.select_related("dataset").filter(
            created_at__date__gte=start_date,
            action__in=DATASET_VIEW_ACTIONS,
        )

        totals = {
            "total_views": queryset.count(),
            "unique_datasets": queryset.values("dataset_id").distinct().count(),
            "unique_files": queryset.exclude(target_id__isnull=True)
            .values("target_id")
            .distinct()
            .count(),
            "preview_views": queryset.filter(action="file_previewed").count(),
            "data_views": queryset.filter(action="file_data_accessed").count(),
            "schema_views": queryset.filter(action="file_schema_accessed").count(),
        }
        by_day_rows = list(
            queryset.annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(total_views=Count("id"))
            .order_by("date")
        )
        top_datasets = _serialize_top_dataset_counts(
            list(
                queryset.values("dataset_id", "dataset__slug")
                .annotate(count=Count("id"))
                .order_by("-count", "dataset__slug")[:ADMIN_ANALYTICS_TOP_LIMIT]
            )
        )

        serializer = self.serializer_class(
            {
                "days": days,
                "totals": totals,
                "by_day": _fill_daily_series(
                    by_day_rows,
                    start_date,
                    days,
                    {"total_views": 0},
                ),
                "top_datasets": top_datasets,
            }
        )
        return success_response(data=serializer.data)


class AdminDashboardDatasetActivitySummaryAPIView(AdminAnalyticsBaseAPIView):
    serializer_class = AdminDatasetActivitySummarySerializer

    @extend_schema(
        tags=["Administration"],
        operation_id="admin_dashboard_dataset_activity_summary",
        summary="Get admin dataset activity aggregation",
        description=(
            "Return aggregated dataset management activity for the requested trailing day window, "
            "excluding end-user download and view access events."
        ),
        parameters=[ADMIN_ANALYTICS_DAYS_PARAMETER],
        responses={
            200: success_response_schema(
                "AdminDashboardDatasetActivitySummarySuccessResponse",
                AdminDatasetActivitySummarySerializer,
                description="Admin dataset activity aggregation returned successfully.",
            ),
            **standard_error_responses(
                "AdminDashboardDatasetActivitySummary",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        days, start_date = self.get_analytics_window()
        queryset = DatasetAuditLog.objects.select_related("dataset").filter(
            created_at__date__gte=start_date,
        ).exclude(action__in=DATASET_ACTIVITY_EXCLUDED_ACTIONS)

        totals = {
            "total_events": queryset.count(),
            "unique_datasets": queryset.values("dataset_id").distinct().count(),
            "dataset_events": queryset.filter(action__in=DATASET_RECORD_ACTIONS).count(),
            "workflow_events": queryset.filter(action__in=DATASET_WORKFLOW_ACTIONS).count(),
            "file_events": queryset.filter(action__startswith="file_").count(),
            "metadata_events": queryset.filter(action__startswith="metadata_").count(),
            "tag_events": queryset.filter(action__startswith="tag_").count(),
            "version_events": queryset.filter(action__startswith="version_").count(),
        }
        by_day_rows = list(
            queryset.annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(total_events=Count("id"))
            .order_by("date")
        )
        by_action = list(
            queryset.values("action")
            .annotate(count=Count("id"))
            .order_by("-count", "action")
        )
        top_datasets = _serialize_top_dataset_counts(
            list(
                queryset.values("dataset_id", "dataset__slug")
                .annotate(count=Count("id"))
                .order_by("-count", "dataset__slug")[:ADMIN_ANALYTICS_TOP_LIMIT]
            )
        )

        serializer = self.serializer_class(
            {
                "days": days,
                "totals": totals,
                "by_day": _fill_daily_series(
                    by_day_rows,
                    start_date,
                    days,
                    {"total_events": 0},
                ),
                "by_action": by_action,
                "top_datasets": top_datasets,
            }
        )
        return success_response(data=serializer.data)


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
        description=(
            "Change the authenticated user's password by providing the current "
            "password and a new password. All outstanding refresh tokens and "
            "existing access tokens for that user are revoked."
        ),
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
        invalidate_user_tokens(request.user)
        issue_csrf_token(request, rotate=True)
        response = success_response(message="Password changed successfully.")
        clear_auth_token_cookies(response)
        return response


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
        description=(
            "Complete a password reset by submitting a valid password reset "
            "token and a new password. All outstanding refresh tokens and "
            "existing access tokens for that user are revoked."
        ),
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
        invalidate_user_tokens(user)
        issue_csrf_token(request, rotate=True)
        response = success_response(message="Password reset successfully.")
        clear_auth_token_cookies(response)
        return response


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
        description=(
            "Deactivate a user account without deleting the underlying user "
            "record. All outstanding refresh tokens and existing access tokens "
            "for that user are revoked."
        ),
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
            invalidate_user_tokens(user)
            return success_response(
                data=UserAdminDetailSerializer(user).data,
                message="User is already inactive.",
            )

        user.is_active = False
        user.save(update_fields=["is_active"])
        invalidate_user_tokens(user)
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
