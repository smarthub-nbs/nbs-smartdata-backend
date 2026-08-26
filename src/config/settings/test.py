"""Test settings for Smarthub."""

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK, build_postgres_database, config


SECRET_KEY = config("SECRET_KEY", default="test-secret-key")
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

DATABASES = {
    "default": build_postgres_database(default_host="localhost"),
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

AUTH_ACCESS_COOKIE_SECURE = False
AUTH_REFRESH_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

DEFAULT_LOCAL_FRONTEND_ORIGINS = ()
CONFIGURED_CORS_ALLOWED_ORIGINS = ()
CORS_ALLOWED_ORIGINS = ()
CONFIGURED_CSRF_TRUSTED_ORIGINS = ()
CSRF_TRUSTED_ORIGINS = ()

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "anon": "100000/hour",
        "user": "100000/hour",
        "auth_csrf": "100000/minute",
        "auth_sensitive": "100000/minute",
        "auth_refresh": "100000/minute",
    },
}
