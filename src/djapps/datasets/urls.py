from django.urls import path
from rest_framework import routers

from djapps.datasets.views import (
    CategoryView,
    DatasetAdminQueueView,
    DatasetAdminQueueSummaryView,
    DatasetDetailView,
    DatasetFileView,
    DatasetMetadataView,
    DatasetPublishView,
    DatasetReviewView,
    DatasetSubmitReviewView,
    DatasetStatusHistoryView,
    DatasetTagView,
    DatasetAuditLogView,
    DatasetVersionView,
    DatasetView,
    IndexingStatusView,
    TagView,
)

router = routers.DefaultRouter()
router.register(r"categories", CategoryView, basename="dataset-category")
router.register(r"tags", TagView, basename="dataset-tag-taxonomy")
router.register(r"versions", DatasetVersionView, basename="dataset-version")
router.register(r"files", DatasetFileView, basename="dataset-file")
router.register(r"tag-links", DatasetTagView, basename="dataset-tag-link")
router.register(r"metadata", DatasetMetadataView, basename="dataset-metadata")
router.register(r"status-history", DatasetStatusHistoryView, basename="dataset-status-history")
router.register(r"indexing-status", IndexingStatusView, basename="dataset-indexing-status")
router.register(r"audit-logs", DatasetAuditLogView, basename="dataset-audit-log")

urlpatterns = [
    path("", DatasetView.as_view(), name="dataset-list-create"),
    path("admin-queue/", DatasetAdminQueueView.as_view(), name="dataset-admin-queue"),
    path(
        "admin-queue/summary/",
        DatasetAdminQueueSummaryView.as_view(),
        name="dataset-admin-queue-summary",
    ),
    path("<uuid:dataset_id>/", DatasetDetailView.as_view(), name="dataset-detail"),
    path(
        "<uuid:dataset_id>/submit-review/",
        DatasetSubmitReviewView.as_view(),
        name="dataset-submit-review",
    ),
    path(
        "<uuid:dataset_id>/review/",
        DatasetReviewView.as_view(),
        name="dataset-review",
    ),
    path(
        "<uuid:dataset_id>/publish/",
        DatasetPublishView.as_view(),
        name="dataset-publish",
    ),
]

urlpatterns += router.urls
