"""Development settings for Smarthub."""

from .base import *  # noqa: F403
from .base import (
    SECRET_KEY,
    Csv,
    INSTALLED_APPS,
    MIDDLEWARE,
    build_csrf_trusted_origins,
    build_postgres_database,
    config,
    configured_tuple,
    local_frontend_origins,
    merge_unique,
)


SECRET_KEY = config("SECRET_KEY", default=SECRET_KEY)
DEBUG = config("DEBUG", cast=bool, default=True)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    cast=Csv(),
    default="localhost,127.0.0.1,0.0.0.0,pixyish-chae-doziest.ngrok-free.dev",
)

DATABASES = {
    "default": build_postgres_database(default_host="localhost"),
}

AUTH_ACCESS_COOKIE_SECURE = config(
    "AUTH_ACCESS_COOKIE_SECURE",
    cast=bool,
    default=not DEBUG,
)
AUTH_REFRESH_COOKIE_SECURE = config(
    "AUTH_REFRESH_COOKIE_SECURE",
    cast=bool,
    default=not DEBUG,
)

DEFAULT_LOCAL_FRONTEND_ORIGINS = local_frontend_origins(DEBUG)
CONFIGURED_CORS_ALLOWED_ORIGINS = configured_tuple("CORS_ALLOWED_ORIGINS")
CORS_ALLOWED_ORIGINS = merge_unique(
    DEFAULT_LOCAL_FRONTEND_ORIGINS,
    CONFIGURED_CORS_ALLOWED_ORIGINS,
)

CONFIGURED_CSRF_TRUSTED_ORIGINS = configured_tuple("CSRF_TRUSTED_ORIGINS")
CSRF_TRUSTED_ORIGINS = build_csrf_trusted_origins(DEBUG, CORS_ALLOWED_ORIGINS)
CSRF_COOKIE_SECURE = config(
    "CSRF_COOKIE_SECURE",
    cast=bool,
    default=AUTH_REFRESH_COOKIE_SECURE,
)

INSTALLED_APPS += ["debug_toolbar"]

MIDDLEWARE.insert(1, "debug_toolbar.middleware.DebugToolbarMiddleware")

INTERNAL_IPS = [
    "127.0.0.1",
    "localhost",
]
