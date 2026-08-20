"""Production settings for Smarthub."""

from .base import *  # noqa: F403
from .base import (
    Csv,
    build_csrf_trusted_origins,
    build_postgres_database,
    config,
    configured_tuple,
    merge_unique,
)


SECRET_KEY = config("SECRET_KEY")
DEBUG = False

ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

DATABASES = {
    "default": build_postgres_database(
        conn_max_age=config("DB_CONN_MAX_AGE", cast=int, default=60),
        require_env=True,
    ),
}

AUTH_ACCESS_COOKIE_SECURE = config(
    "AUTH_ACCESS_COOKIE_SECURE",
    cast=bool,
    default=True,
)
AUTH_REFRESH_COOKIE_SECURE = config(
    "AUTH_REFRESH_COOKIE_SECURE",
    cast=bool,
    default=True,
)

DEFAULT_LOCAL_FRONTEND_ORIGINS = ()
CONFIGURED_CORS_ALLOWED_ORIGINS = configured_tuple("CORS_ALLOWED_ORIGINS")
CORS_ALLOWED_ORIGINS = merge_unique(CONFIGURED_CORS_ALLOWED_ORIGINS)

CONFIGURED_CSRF_TRUSTED_ORIGINS = configured_tuple("CSRF_TRUSTED_ORIGINS")
CSRF_TRUSTED_ORIGINS = build_csrf_trusted_origins(DEBUG, CORS_ALLOWED_ORIGINS)
CSRF_COOKIE_SECURE = config(
    "CSRF_COOKIE_SECURE",
    cast=bool,
    default=True,
)

SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", cast=bool, default=True)
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", cast=bool, default=True)
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", cast=int, default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    cast=bool,
    default=True,
)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", cast=bool, default=True)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
