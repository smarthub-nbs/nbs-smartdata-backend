from django.urls import path

from djapps.tisp.views import TispCachedSearchView


urlpatterns = [
    path("search/tisp-cache/", TispCachedSearchView.as_view(), name="tisp-cached-search"),
]

