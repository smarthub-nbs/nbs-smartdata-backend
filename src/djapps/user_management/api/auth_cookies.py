from datetime import datetime, timezone as datetime_timezone

from django.conf import settings
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


def get_refresh_token_from_request(request, *, required=True):
    return _get_token_from_request(
        request,
        settings.AUTH_REFRESH_COOKIE_NAME,
        error_key="refresh",
        error_message="Refresh token cookie is missing.",
        required=required,
    )


def get_access_token_from_request(request, *, required=True):
    return _get_token_from_request(
        request,
        settings.AUTH_ACCESS_COOKIE_NAME,
        error_key="access",
        error_message="Access token cookie is missing.",
        required=required,
    )


def set_refresh_token_cookie(response, refresh_token):
    _set_token_cookie(
        response,
        cookie_name=settings.AUTH_REFRESH_COOKIE_NAME,
        raw_token=refresh_token,
        token_class=RefreshToken,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        domain=settings.AUTH_REFRESH_COOKIE_DOMAIN,
        secure=settings.AUTH_REFRESH_COOKIE_SECURE,
        httponly=settings.AUTH_REFRESH_COOKIE_HTTP_ONLY,
        samesite=settings.AUTH_REFRESH_COOKIE_SAMESITE,
    )


def clear_refresh_token_cookie(response):
    _clear_cookie(
        response,
        cookie_name=settings.AUTH_REFRESH_COOKIE_NAME,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        domain=settings.AUTH_REFRESH_COOKIE_DOMAIN,
        samesite=settings.AUTH_REFRESH_COOKIE_SAMESITE,
    )


def set_access_token_cookie(response, access_token):
    _set_token_cookie(
        response,
        cookie_name=settings.AUTH_ACCESS_COOKIE_NAME,
        raw_token=access_token,
        token_class=AccessToken,
        path=settings.AUTH_ACCESS_COOKIE_PATH,
        domain=settings.AUTH_ACCESS_COOKIE_DOMAIN,
        secure=settings.AUTH_ACCESS_COOKIE_SECURE,
        httponly=settings.AUTH_ACCESS_COOKIE_HTTP_ONLY,
        samesite=settings.AUTH_ACCESS_COOKIE_SAMESITE,
    )


def clear_access_token_cookie(response):
    _clear_cookie(
        response,
        cookie_name=settings.AUTH_ACCESS_COOKIE_NAME,
        path=settings.AUTH_ACCESS_COOKIE_PATH,
        domain=settings.AUTH_ACCESS_COOKIE_DOMAIN,
        samesite=settings.AUTH_ACCESS_COOKIE_SAMESITE,
    )


def set_auth_token_cookies(response, *, access_token, refresh_token=None):
    set_access_token_cookie(response, access_token)
    if refresh_token:
        set_refresh_token_cookie(response, refresh_token)


def clear_auth_token_cookies(response):
    clear_access_token_cookie(response)
    clear_refresh_token_cookie(response)


def _get_token_from_request(
    request,
    cookie_name,
    *,
    error_key,
    error_message,
    required,
):
    raw_token = request.COOKIES.get(cookie_name)
    if raw_token:
        return raw_token

    if required:
        raise ValidationError({error_key: [error_message]})

    return None


def _set_token_cookie(
    response,
    *,
    cookie_name,
    raw_token,
    token_class,
    path,
    domain,
    secure,
    httponly,
    samesite,
):
    token = token_class(raw_token)
    expires_at = datetime.fromtimestamp(token["exp"], tz=datetime_timezone.utc)

    response.set_cookie(
        cookie_name,
        raw_token,
        expires=expires_at,
        path=path,
        domain=domain,
        secure=secure,
        httponly=httponly,
        samesite=samesite,
    )


def _clear_cookie(response, *, cookie_name, path, domain, samesite):
    response.delete_cookie(
        cookie_name,
        path=path,
        domain=domain,
        samesite=samesite,
    )
