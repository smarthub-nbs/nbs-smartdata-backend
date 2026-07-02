from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class VersionedJWTAuthentication(JWTAuthentication):
    token_version_claim = "token_version"

    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
            if raw_token is not None:
                validated_token = self.get_validated_token(raw_token)
                return self._build_auth_result(
                    request,
                    validated_token,
                    enforce_csrf=False,
                )

        cookie_token = request.COOKIES.get(settings.AUTH_ACCESS_COOKIE_NAME)
        if not cookie_token:
            return None

        try:
            validated_token = self.get_validated_token(cookie_token)
            return self._build_auth_result(
                request,
                validated_token,
                enforce_csrf=self._should_enforce_csrf(request),
            )
        except AuthenticationFailed:
            return None

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        token_version = self._get_token_version(validated_token)
        if token_version != user.token_version:
            raise AuthenticationFailed(
                "Token has been revoked.",
                code="token_revoked",
            )
        return user

    def _get_token_version(self, validated_token):
        raw_value = validated_token.get(self.token_version_claim, 0)
        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise AuthenticationFailed(
                "Token contained an invalid version claim.",
                code="token_not_valid",
            ) from exc

    def _build_auth_result(self, request, validated_token, *, enforce_csrf):
        user = self.get_user(validated_token)
        if enforce_csrf:
            SessionAuthentication().enforce_csrf(request)
        return user, validated_token

    def _should_enforce_csrf(self, request):
        return request.method not in ("GET", "HEAD", "OPTIONS", "TRACE")
