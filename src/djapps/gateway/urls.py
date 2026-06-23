from django.urls import path

from djapps.gateway.views import (
    OpenCategoryListAPIView,
    OpenDatasetChangeListAPIView,
    OpenDatasetDetailAPIView,
    OpenDatasetDownloadAPIView,
    OpenDatasetFacetsAPIView,
    OpenDatasetFileDownloadAPIView,
    OpenDatasetFileDataAPIView,
    OpenDatasetFileListAPIView,
    OpenDatasetFilePreviewAPIView,
    OpenDatasetFileSchemaAPIView,
    OpenDatasetFormatListAPIView,
    OpenDatasetFrequencyListAPIView,
    OpenDatasetLatestDataAPIView,
    OpenDatasetLatestVersionAPIView,
    OpenDatasetLicenseListAPIView,
    OpenDatasetListAPIView,
    OpenDatasetMetadataAPIView,
    OpenDatasetPublisherListAPIView,
    OpenDatasetRegionListAPIView,
    OpenDatasetStatsAPIView,
    OpenDatasetVersionDetailAPIView,
    OpenDatasetVersionListAPIView,
    OpenTagListAPIView,
)


urlpatterns = [
    path("categories/", OpenCategoryListAPIView.as_view(), name="gateway-category-list"),
    path("tags/", OpenTagListAPIView.as_view(), name="gateway-tag-list"),
    path("licenses/", OpenDatasetLicenseListAPIView.as_view(), name="gateway-dataset-license-list"),
    path("publishers/", OpenDatasetPublisherListAPIView.as_view(), name="gateway-dataset-publisher-list"),
    path("frequencies/", OpenDatasetFrequencyListAPIView.as_view(), name="gateway-dataset-frequency-list"),
    path("regions/", OpenDatasetRegionListAPIView.as_view(), name="gateway-dataset-region-list"),
    path("datasets/", OpenDatasetListAPIView.as_view(), name="gateway-dataset-list"),
    path("datasets/facets/", OpenDatasetFacetsAPIView.as_view(), name="gateway-dataset-facets"),
    path("datasets/changes/", OpenDatasetChangeListAPIView.as_view(), name="gateway-dataset-change-list"),
    path("datasets/formats/", OpenDatasetFormatListAPIView.as_view(), name="gateway-dataset-format-list"),
    path(
        "datasets/<str:dataset_lookup>/versions/<uuid:version_id>/",
        OpenDatasetVersionDetailAPIView.as_view(),
        name="gateway-dataset-version-detail",
    ),
    path(
        "datasets/<str:dataset_lookup>/versions/",
        OpenDatasetVersionListAPIView.as_view(),
        name="gateway-dataset-version-list",
    ),
    path(
        "datasets/<str:dataset_lookup>/latest/data/",
        OpenDatasetLatestDataAPIView.as_view(),
        name="gateway-dataset-latest-data",
    ),
    path(
        "datasets/<str:dataset_lookup>/latest/",
        OpenDatasetLatestVersionAPIView.as_view(),
        name="gateway-dataset-latest-version",
    ),
    path(
        "datasets/<str:dataset_lookup>/stats/",
        OpenDatasetStatsAPIView.as_view(),
        name="gateway-dataset-stats",
    ),
    path(
        "datasets/<str:dataset_lookup>/download/",
        OpenDatasetDownloadAPIView.as_view(),
        name="gateway-dataset-download",
    ),
    path(
        "datasets/<str:dataset_lookup>/files/",
        OpenDatasetFileListAPIView.as_view(),
        name="gateway-dataset-file-list",
    ),
    path(
        "datasets/<str:dataset_lookup>/",
        OpenDatasetDetailAPIView.as_view(),
        name="gateway-dataset-detail",
    ),
    path(
        "datasets/<str:dataset_lookup>/metadata/",
        OpenDatasetMetadataAPIView.as_view(),
        name="gateway-dataset-metadata",
    ),
    path(
        "files/<uuid:file_id>/preview/",
        OpenDatasetFilePreviewAPIView.as_view(),
        name="gateway-dataset-file-preview",
    ),
    path(
        "files/<uuid:file_id>/schema/",
        OpenDatasetFileSchemaAPIView.as_view(),
        name="gateway-dataset-file-schema",
    ),
    path(
        "files/<uuid:file_id>/download/",
        OpenDatasetFileDownloadAPIView.as_view(),
        name="gateway-dataset-file-download",
    ),
    path(
        "files/<uuid:file_id>/data/",
        OpenDatasetFileDataAPIView.as_view(),
        name="gateway-dataset-file-data",
    ),
]
