from django.urls import path

from .views import (
    AdminAPIView,
    DeveloperAPIView,
    EditorAPIView,
    GitHubSocialLoginAPIView,
    GoogleSocialLoginAPIView,
    LegacyMeAPIView,
    LoginAPIView,
    LogoutAPIView,
    MeAPIView,
    PermissionProtectedAPIView,
    PublicPingAPIView,
    RefreshAPIView,
    RegisteredUserAPIView,
    RegisterAPIView,
    ResearcherAPIView,
)

prefix = "api/v1/"

urlpatterns = [
    path("ping/", PublicPingAPIView.as_view(), name="api-ping"),
    path("auth/register/", RegisterAPIView.as_view(), name="api-auth-register"),
    path("auth/login/", LoginAPIView.as_view(), name="api-auth-login"),
    path(
        "auth/social/google/",
        GoogleSocialLoginAPIView.as_view(),
        name="api-auth-social-google",
    ),
    path(
        "auth/social/github/",
        GitHubSocialLoginAPIView.as_view(),
        name="api-auth-social-github",
    ),
    path("auth/refresh/", RefreshAPIView.as_view(), name="api-auth-refresh"),
    path("auth/logout/", LogoutAPIView.as_view(), name="api-auth-logout"),
    path("auth/me/", MeAPIView.as_view(), name="api-auth-me"),
    path("me/", LegacyMeAPIView.as_view(), name="api-me"),
    path("registered/", RegisteredUserAPIView.as_view(), name="api-registered"),
    path("editor/", EditorAPIView.as_view(), name="api-editor"),
    path("developer/", DeveloperAPIView.as_view(), name="api-developer"),
    path("researcher/", ResearcherAPIView.as_view(), name="api-researcher"),
    path("admin/", AdminAPIView.as_view(), name="api-admin"),
    path("permission/", PermissionProtectedAPIView.as_view(), name="api-permission"),
]
