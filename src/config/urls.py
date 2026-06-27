"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

prefix = "api/v1"

urlpatterns = [
    path("admin/", admin.site.urls),
    path('schema-viewer/', include('schema_viewer.urls')),
    path(f"{prefix}/schema/", SpectacularAPIView.as_view(), name='schema'),
    path('', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path(f"{prefix}/", include("djapps.user_management.api.urls")),
    path(f"{prefix}/gateway/", include("djapps.gateway.urls")),
    path(f"{prefix}/developer/", include("djapps.gateway.developer_urls")),
    path(f"{prefix}/dataset/", include("djapps.datasets.urls")),
]
