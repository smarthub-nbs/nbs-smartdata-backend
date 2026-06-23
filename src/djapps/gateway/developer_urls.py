from django.urls import path

from djapps.gateway.views import (
    DeveloperAPIKeyDetailAPIView,
    DeveloperAPIKeyListAPIView,
    DeveloperAPIKeyRegenerateAPIView,
    DeveloperAPIKeyRequestAPIView,
    DeveloperAPIKeyRevokeAPIView,
    DeveloperAPIKeyUsageAPIView,
    DeveloperAPIUsageAPIView,
)


urlpatterns = [
    path("api-keys/request/", DeveloperAPIKeyRequestAPIView.as_view(), name="developer-api-key-request"),
    path("api-keys/", DeveloperAPIKeyListAPIView.as_view(), name="developer-api-key-list"),
    path("api-keys/<uuid:id>/", DeveloperAPIKeyDetailAPIView.as_view(), name="developer-api-key-detail"),
    path(
        "api-keys/<uuid:id>/regenerate/",
        DeveloperAPIKeyRegenerateAPIView.as_view(),
        name="developer-api-key-regenerate",
    ),
    path(
        "api-keys/<uuid:id>/revoke/",
        DeveloperAPIKeyRevokeAPIView.as_view(),
        name="developer-api-key-revoke",
    ),
    path(
        "api-keys/<uuid:id>/usage/",
        DeveloperAPIKeyUsageAPIView.as_view(),
        name="developer-api-key-usage",
    ),
    path("api-usage/", DeveloperAPIUsageAPIView.as_view(), name="developer-api-usage"),
]
