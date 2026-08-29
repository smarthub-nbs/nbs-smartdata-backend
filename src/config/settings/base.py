"""
Base Django settings for Smarthub.

Environment-specific modules import from here and override only the settings
that should differ between development, tests, and production.
"""

from datetime import timedelta
from pathlib import Path

from decouple import Csv, config
from django.urls import reverse_lazy


BASE_DIR = Path(__file__).resolve().parent.parent


def normalize_samesite(value):
    value = (value or "").strip()
    return {
        "lax": "Lax",
        "strict": "Strict",
        "none": "None",
    }.get(value.lower(), value)


def configured_tuple(name, default=""):
    return tuple(
        item.strip()
        for item in config(name, default=default).split(",")
        if item.strip()
    )


def merge_unique(*groups):
    items = []
    for group in groups:
        items.extend(item for item in group if item)
    return tuple(dict.fromkeys(items))


def local_frontend_origins(debug):
    if not debug:
        return ()
    return (
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    )


def build_cors_allowed_origins(debug):
    return merge_unique(
        local_frontend_origins(debug),
        configured_tuple("CORS_ALLOWED_ORIGINS"),
    )


def build_csrf_trusted_origins(debug, cors_allowed_origins):
    origins = merge_unique(
        local_frontend_origins(debug),
        configured_tuple("CSRF_TRUSTED_ORIGINS"),
    )
    return origins or cors_allowed_origins


def build_postgres_database(
    *,
    default_name="smarthub",
    default_user="smarthub",
    default_password="change-me",
    default_host="localhost",
    default_port="5432",
    conn_max_age=0,
    require_env=False,
):
    def env(name, default):
        if require_env:
            return config(name)
        return config(name, default=default)

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default_name),
        "USER": env("DB_USER", default_user),
        "PASSWORD": env("DB_PASSWORD", default_password),
        "HOST": env("DB_HOST", default_host),
        "PORT": env("DB_PORT", default_port),
        "CONN_MAX_AGE": conn_max_age,
        "OPTIONS": {
            "pool": {
                "min_size": config("DB_POOL_MIN_SIZE", cast=int, default=2),
                "max_size": config("DB_POOL_MAX_SIZE", cast=int, default=10),
                "timeout": config("DB_POOL_TIMEOUT", cast=int, default=30),
            }
        },
    }


SECRET_KEY = config("SECRET_KEY", default="django-insecure-smarthub-local-dev-key")
DEBUG = False
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    cast=Csv(),
    default="localhost,127.0.0.1",
)


INSTALLED_APPS = [
    "corsheaders",
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "schema_viewer",
    "djapps.ai.apps.AiConfig",
    "djapps.tisp.apps.TispConfig",
    "djapps.user_management.apps.UserManagementConfig",
    "djapps.datasets.apps.DatasetsConfig",
    "djapps.gateway.apps.GatewayConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "config.api.middleware.RequestIDMiddleware",
    # "config.api.middleware.FrontendCredentialCorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": build_postgres_database(),
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "djapps.user_management.password_validators.StrongPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="no-reply@smarthub.local")

DATASET_MAX_UPLOAD_SIZE = config(
    "DATASET_MAX_UPLOAD_SIZE",
    cast=int,
    default=50 * 1024 * 1024,
)
DATASET_ALLOWED_FILE_EXTENSIONS = tuple(
    item.strip().lower()
    for item in config(
        "DATASET_ALLOWED_FILE_EXTENSIONS",
        default=".csv,.json,.pdf,.tsv,.txt,.xls,.xlsx,.xml,.sdmx,.zip",
    ).split(",")
    if item.strip()
)

OPENAI_API_KEY = config("OPENAI_API_KEY", default="")
OPENAI_MODEL = config("OPENAI_MODEL", default="gpt-4.1-mini")
OPENAI_TIMEOUT_SECONDS = config("OPENAI_TIMEOUT_SECONDS", cast=int, default=20)
TISP_CACHE_TTL_SECONDS = config("TISP_CACHE_TTL_SECONDS", cast=int, default=60 * 60 * 24)
TISP_FETCH_TIMEOUT_SECONDS = config("TISP_FETCH_TIMEOUT_SECONDS", cast=int, default=20)

AUTH_USER_MODEL = "user_management.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "djapps.user_management.api.authentication.VersionedJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": config("DRF_THROTTLE_ANON_RATE", default="100/hour"),
        "user": config("DRF_THROTTLE_USER_RATE", default="1000/day"),
        "auth_csrf": config("DRF_THROTTLE_AUTH_CSRF_RATE", default="120/minute"),
        "auth_sensitive": config(
            "DRF_THROTTLE_AUTH_SENSITIVE_RATE",
            default="20/minute",
        ),
        "auth_refresh": config("DRF_THROTTLE_AUTH_REFRESH_RATE", default="60/minute"),
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "config.api.exceptions.standardized_exception_handler",
}

SIMPLE_JWT = {
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", cast=int, default=15)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("JWT_REFRESH_TOKEN_LIFETIME_DAYS", cast=int, default=7)
    ),
    "ROTATE_REFRESH_TOKENS": config(
        "JWT_ROTATE_REFRESH_TOKENS",
        cast=bool,
        default=True,
    ),
    "BLACKLIST_AFTER_ROTATION": config(
        "JWT_BLACKLIST_AFTER_ROTATION",
        cast=bool,
        default=True,
    ),
}

AUTH_ACCESS_COOKIE_NAME = config(
    "AUTH_ACCESS_COOKIE_NAME",
    default="smarthub_access_token",
)
AUTH_ACCESS_COOKIE_SECURE = True
AUTH_ACCESS_COOKIE_HTTP_ONLY = True
AUTH_ACCESS_COOKIE_SAMESITE = normalize_samesite(
    config("AUTH_ACCESS_COOKIE_SAMESITE", default="Lax")
)
AUTH_ACCESS_COOKIE_PATH = config(
    "AUTH_ACCESS_COOKIE_PATH",
    default="/api/v1/",
)
AUTH_ACCESS_COOKIE_DOMAIN = (
    config("AUTH_ACCESS_COOKIE_DOMAIN", default="").strip() or None
)

AUTH_REFRESH_COOKIE_NAME = config(
    "AUTH_REFRESH_COOKIE_NAME",
    default="smarthub_refresh_token",
)
AUTH_REFRESH_COOKIE_SECURE = True
AUTH_REFRESH_COOKIE_HTTP_ONLY = True
AUTH_REFRESH_COOKIE_SAMESITE = normalize_samesite(
    config("AUTH_REFRESH_COOKIE_SAMESITE", default=AUTH_ACCESS_COOKIE_SAMESITE)
)
AUTH_REFRESH_COOKIE_PATH = config(
    "AUTH_REFRESH_COOKIE_PATH",
    default="/api/v1/auth/",
)
AUTH_REFRESH_COOKIE_DOMAIN = (
    config("AUTH_REFRESH_COOKIE_DOMAIN", default="").strip()
    or AUTH_ACCESS_COOKIE_DOMAIN
)

DEFAULT_LOCAL_FRONTEND_ORIGINS = local_frontend_origins(DEBUG)
CONFIGURED_CORS_ALLOWED_ORIGINS = configured_tuple("CORS_ALLOWED_ORIGINS")
CORS_ALLOWED_ORIGINS = merge_unique(
    DEFAULT_LOCAL_FRONTEND_ORIGINS,
    CONFIGURED_CORS_ALLOWED_ORIGINS,
)
CORS_ALLOW_CREDENTIALS = config(
    "CORS_ALLOW_CREDENTIALS",
    cast=bool,
    default=True,
)
CORS_ALLOW_HEADERS = (
    "Accept",
    "Authorization",
    "Content-Type",
    "X-CSRFToken",
    "X-Request-ID",
)
CORS_ALLOW_METHODS = (
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
)
CORS_EXPOSE_HEADERS = (
    "X-Request-ID",
)
CORS_PREFLIGHT_MAX_AGE = config(
    "CORS_PREFLIGHT_MAX_AGE",
    cast=int,
    default=86400,
)


SESSION_COOKIE_SECURE = config(
    "SESSION_COOKIE_SECURE",
    cast=bool,
    default=True,
)
SESSION_COOKIE_SAMESITE = config(
    "SESSION_COOKIE_SAMESITE",
    default=AUTH_REFRESH_COOKIE_SAMESITE,
)

CONFIGURED_CSRF_TRUSTED_ORIGINS = configured_tuple("CSRF_TRUSTED_ORIGINS")
CSRF_TRUSTED_ORIGINS = build_csrf_trusted_origins(DEBUG, CORS_ALLOWED_ORIGINS)
CSRF_COOKIE_NAME = config("CSRF_COOKIE_NAME", default="csrftoken")
CSRF_COOKIE_SECURE = config(
    "CSRF_COOKIE_SECURE",
    cast=bool,
    default=True,
)
CSRF_COOKIE_HTTPONLY = config(
    "CSRF_COOKIE_HTTPONLY",
    cast=bool,
    default=False,
)
CSRF_COOKIE_SAMESITE = normalize_samesite(
    config("CSRF_COOKIE_SAMESITE", default=AUTH_REFRESH_COOKIE_SAMESITE)
)
CSRF_COOKIE_PATH = config(
    "CSRF_COOKIE_PATH",
    default="/",
)
CSRF_COOKIE_DOMAIN = (
    config("CSRF_COOKIE_DOMAIN", default="").strip() or AUTH_REFRESH_COOKIE_DOMAIN
)

GITHUB_OAUTH_CLIENT_ID = config("GITHUB_OAUTH_CLIENT_ID", default="")
GITHUB_OAUTH_CLIENT_SECRET = config("GITHUB_OAUTH_CLIENT_SECRET", default="")
GITHUB_OAUTH_ALLOWED_REDIRECT_URIS = configured_tuple(
    "GITHUB_OAUTH_ALLOWED_REDIRECT_URIS"
)

CELERY_BROKER_URL = config(
    "CELERY_BROKER_URL",
    default="redis://localhost:6379/0",
)
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND",
    default=CELERY_BROKER_URL,
)
CELERY_ACCEPT_CONTENT = ("json",)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = config(
    "CELERY_TASK_TRACK_STARTED",
    cast=bool,
    default=True,
)
CELERY_TASK_ALWAYS_EAGER = config(
    "CELERY_TASK_ALWAYS_EAGER",
    cast=bool,
    default=False,
)
CELERY_TASK_EAGER_PROPAGATES = config(
    "CELERY_TASK_EAGER_PROPAGATES",
    cast=bool,
    default=False,
)
CELERY_TASK_DEFAULT_QUEUE = config(
    "CELERY_TASK_DEFAULT_QUEUE",
    default="default",
)
CELERY_WORKER_PREFETCH_MULTIPLIER = config(
    "CELERY_WORKER_PREFETCH_MULTIPLIER",
    cast=int,
    default=1,
)
CELERY_TASK_TIME_LIMIT = config(
    "CELERY_TASK_TIME_LIMIT",
    cast=int,
    default=1800,
)
CELERY_TASK_SOFT_TIME_LIMIT = config(
    "CELERY_TASK_SOFT_TIME_LIMIT",
    cast=int,
    default=1500,
)

PASSWORD_RESET_TOKEN_MAX_AGE = config(
    "PASSWORD_RESET_TOKEN_MAX_AGE",
    cast=int,
    default=3600,
)
EMAIL_VERIFICATION_TOKEN_MAX_AGE = config(
    "EMAIL_VERIFICATION_TOKEN_MAX_AGE",
    cast=int,
    default=86400,
)
FRONTEND_PASSWORD_RESET_URL = config("FRONTEND_PASSWORD_RESET_URL", default="")
FRONTEND_EMAIL_VERIFICATION_URL = config("FRONTEND_EMAIL_VERIFICATION_URL", default="")

SPECTACULAR_SETTINGS = {
    "TITLE": "Smarthub Project API",
    "DESCRIPTION": (
        "APIs for SmartHub. "
        "Protected endpoints accept JWT bearer access tokens with the header "
        "`Authorization: Bearer <access_token>` or an HttpOnly access-token cookie. "
        "Access and refresh tokens are issued in HttpOnly cookies. "
        "Successful responses are wrapped as `{success, message, data}` and "
        "errors are wrapped as `{success: false, error: {...}}`."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "PREPROCESSING_HOOKS": [
        "config.api.spectacular.keep_canonical_api_endpoints",
    ],
    "SORT_OPERATIONS": True,
    "SORT_OPERATION_PARAMETERS": True,
    "TAGS": [
        {
            "name": "Authentication",
            "description": "JWT and social authentication endpoints.",
        },
        {
            "name": "Authorization",
            "description": "Role and permission protected endpoints.",
        },
        {
            "name": "Datasets",
            "description": "Dataset discovery and core dataset CRUD endpoints.",
        },
        {
            "name": "Dataset Workflow",
            "description": "Review and publication workflow endpoints.",
        },
        {
            "name": "Dataset Taxonomy",
            "description": "Category and tag taxonomy endpoints.",
        },
        {
            "name": "Dataset Files",
            "description": "Dataset file upload, download, and file metadata endpoints.",
        },
        {
            "name": "Dataset Audit",
            "description": "Dataset audit, indexing, and status history endpoints.",
        },
        {
            "name": "Gateway",
            "description": "Public and API-key dataset access endpoints.",
        },
        {
            "name": "Developer API Keys",
            "description": "Developer API key management and usage endpoints.",
        },
    ],
    "SWAGGER_UI_SETTINGS": {
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "docExpansion": "list",
    },
    "ENUM_NAME_OVERRIDES": {
        "DatasetWorkflowStatusEnum": "djapps.datasets.models.DatasetStatus.CHOICES",
        "APIConsumerStatusEnum": "djapps.gateway.models.APIConsumer.STATUS_CHOICES",
        "APIKeyStatusEnum": "djapps.gateway.models.APIKey.STATUS_CHOICES",
        "DatasetBulkActionEnum": (
            "djapps.datasets.serializers.DATASET_ADMIN_BULK_ACTION_CHOICES"
        ),
        "DatasetReviewActionEnum": (
            "djapps.datasets.serializers.DATASET_REVIEW_ACTION_CHOICES"
        ),
        "DatasetFileValidationStatusEnum": (
            "djapps.datasets.models.FileValidationStatus.CHOICES"
        ),
        "DatasetFrequencyEnum": "djapps.datasets.models.DatasetFrequency.CHOICES",
        "APIConsumerTypeEnum": "djapps.gateway.models.APIConsumer.CONSUMER_TYPES",
    },
}

UNFOLD = {
    "SITE_TITLE": "Smarthub Admin",
    "SITE_HEADER": "Smarthub",
    "SITE_SUBHEADER": "Data management and API administration",
    "SITE_SYMBOL": "database",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SHOW_BACK_BUTTON": True,
    "ENVIRONMENT": "config.admin.environment_callback",
    "ENVIRONMENT_TITLE_PREFIX": "config.admin.environment_title_prefix_callback",
    "DASHBOARD_CALLBACK": "config.admin.dashboard_callback",
    "COMMAND": {
        "search_models": [
            "datasets.dataset",
            "datasets.datasetmetadata",
            "datasets.datasetfile",
            "user_management.user",
            "gateway.apiconsumer",
            "gateway.apikey",
        ],
        "show_history": True,
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": "Accounts",
                "separator": True,
                "items": [
                    {
                        "title": "Users",
                        "icon": "group",
                        "link": reverse_lazy(
                            "admin:user_management_user_changelist"
                        ),
                    },
                    {
                        "title": "Groups",
                        "icon": "admin_panel_settings",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                ],
            },
            {
                "title": "Datasets",
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": "Datasets",
                        "icon": "database",
                        "link": reverse_lazy("admin:datasets_dataset_changelist"),
                    },
                    {
                        "title": "Metadata",
                        "icon": "description",
                        "link": reverse_lazy(
                            "admin:datasets_datasetmetadata_changelist"
                        ),
                    },
                    {
                        "title": "Files",
                        "icon": "upload_file",
                        "link": reverse_lazy("admin:datasets_datasetfile_changelist"),
                    },
                    {
                        "title": "Categories",
                        "icon": "category",
                        "link": reverse_lazy("admin:datasets_category_changelist"),
                    },
                    {
                        "title": "Tags",
                        "icon": "sell",
                        "link": reverse_lazy("admin:datasets_tag_changelist"),
                    },
                    {
                        "title": "Regions",
                        "icon": "public",
                        "link": reverse_lazy("admin:datasets_region_changelist"),
                    },
                    {
                        "title": "Bookmarks",
                        "icon": "bookmark",
                        "link": reverse_lazy(
                            "admin:datasets_datasetbookmark_changelist"
                        ),
                    },
                ],
            },
            {
                "title": "Dataset Operations",
                "separator": True,
                "items": [
                    {
                        "title": "Bulk Action Jobs",
                        "icon": "playlist_add_check",
                        "link": reverse_lazy(
                            "admin:datasets_datasetbulkactionjob_changelist"
                        ),
                    },
                    {
                        "title": "Bulk Upload Jobs",
                        "icon": "cloud_upload",
                        "link": reverse_lazy(
                            "admin:datasets_datasetbulkuploadjob_changelist"
                        ),
                    },
                    {
                        "title": "Upload Job Items",
                        "icon": "fact_check",
                        "link": reverse_lazy(
                            "admin:datasets_datasetbulkuploadjobitem_changelist"
                        ),
                    },
                    {
                        "title": "Status History",
                        "icon": "history",
                        "link": reverse_lazy(
                            "admin:datasets_datasetstatushistory_changelist"
                        ),
                    },
                    {
                        "title": "Audit Logs",
                        "icon": "manage_search",
                        "link": reverse_lazy(
                            "admin:datasets_datasetauditlog_changelist"
                        ),
                    },
                    {
                        "title": "Indexing",
                        "icon": "sync",
                        "link": reverse_lazy(
                            "admin:datasets_indexingstatus_changelist"
                        ),
                    },
                ],
            },
            {
                "title": "Gateway",
                "separator": True,
                "items": [
                    {
                        "title": "API Consumers",
                        "icon": "hub",
                        "link": reverse_lazy("admin:gateway_apiconsumer_changelist"),
                    },
                    {
                        "title": "API Keys",
                        "icon": "key",
                        "link": reverse_lazy("admin:gateway_apikey_changelist"),
                    },
                    {
                        "title": "API Scopes",
                        "icon": "rule",
                        "link": reverse_lazy("admin:gateway_apiscope_changelist"),
                    },
                    {
                        "title": "Usage Logs",
                        "icon": "monitoring",
                        "link": reverse_lazy("admin:gateway_apiusagelog_changelist"),
                    },
                ],
            },
            {
                "title": "TISP",
                "separator": True,
                "items": [
                    {
                        "title": "Data Values",
                        "icon": "table_chart",
                        "link": reverse_lazy("admin:tisp_tispdatavalue_changelist"),
                    },
                    {
                        "title": "Census Records",
                        "icon": "map",
                        "link": reverse_lazy("admin:tisp_censusdatarecord_changelist"),
                    },
                    {
                        "title": "Knowledge Documents",
                        "icon": "article",
                        "link": reverse_lazy(
                            "admin:tisp_tispknowledgedocument_changelist"
                        ),
                    },
                    {
                        "title": "API Response Cache",
                        "icon": "cached",
                        "link": reverse_lazy(
                            "admin:tisp_tispapiresponsecache_changelist"
                        ),
                    },
                ],
            },
        ],
    },
}
