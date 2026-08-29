from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone


def environment_callback(request):
    environment = settings.SETTINGS_MODULE.rsplit(".", maxsplit=1)[-1]
    labels = {
        "production": ("Production", "danger"),
        "development": ("Development", "info"),
        "test": ("Test", "warning"),
    }
    return labels.get(environment, (environment.title(), "primary"))


def environment_title_prefix_callback(request):
    return environment_callback(request)[0]


def dashboard_callback(request, context):
    try:
        context.update(_build_dashboard_context())
    except DatabaseError:
        context.update(
            {
                "dashboard_cards": [],
                "dashboard_jobs": [],
                "dashboard_recent_datasets": [],
                "dashboard_cache_items": [],
                "dashboard_error": (
                    "Dashboard metrics are unavailable until the database is ready."
                ),
            }
        )

    return context


def _build_dashboard_context():
    from djapps.datasets.models import (
        Dataset,
        DatasetBulkActionJob,
        DatasetBulkActionJobStatus,
        DatasetBulkUploadJob,
        DatasetStatus,
    )
    from djapps.gateway.models import APIUsageLog
    from djapps.tisp.models import TispApiResponseCache

    since_yesterday = timezone.now() - timedelta(days=1)
    failed_action_jobs = DatasetBulkActionJob.objects.filter(
        status=DatasetBulkActionJobStatus.FAILED
    ).count()
    failed_upload_jobs = DatasetBulkUploadJob.objects.filter(
        status=DatasetBulkActionJobStatus.FAILED
    ).count()

    return {
        "dashboard_cards": [
            {
                "title": "Datasets",
                "value": _format_count(Dataset.objects.count()),
                "icon": "database",
                "description": "Active dataset records",
                "href": reverse("admin:datasets_dataset_changelist"),
            },
            {
                "title": "Published",
                "value": _format_count(
                    Dataset.objects.filter(
                        status=DatasetStatus.PUBLISHED,
                        visibility=True,
                    ).count()
                ),
                "icon": "verified",
                "description": "Visible published datasets",
                "href": (
                    reverse("admin:datasets_dataset_changelist")
                    + "?status__exact=published&visibility__exact=1"
                ),
            },
            {
                "title": "Failed Jobs",
                "value": _format_count(failed_action_jobs + failed_upload_jobs),
                "icon": "error",
                "description": "Bulk jobs needing attention",
                "href": reverse("admin:datasets_datasetbulkuploadjob_changelist"),
            },
            {
                "title": "API Calls",
                "value": _format_count(
                    APIUsageLog.objects.filter(created_at__gte=since_yesterday).count()
                ),
                "icon": "monitoring",
                "description": "Usage log entries in 24h",
                "href": reverse("admin:gateway_apiusagelog_changelist"),
            },
            {
                "title": "TISP Cache",
                "value": _format_count(TispApiResponseCache.objects.count()),
                "icon": "cached",
                "description": "Cached upstream API responses",
                "href": reverse("admin:tisp_tispapiresponsecache_changelist"),
            },
        ],
        "dashboard_jobs": _recent_jobs(),
        "dashboard_recent_datasets": _recent_datasets(),
        "dashboard_cache_items": _recent_tisp_cache(),
    }


def _recent_jobs():
    from djapps.datasets.models import DatasetBulkActionJob, DatasetBulkUploadJob

    action_jobs = (
        DatasetBulkActionJob.objects.select_related("requested_by")
        .order_by("-created_at")[:5]
    )
    upload_jobs = (
        DatasetBulkUploadJob.objects.select_related("requested_by")
        .order_by("-created_at")[:5]
    )
    jobs = [
        {
            "title": f"Bulk action: {job.action}",
            "status": job.status,
            "user": job.requested_by.email,
            "created_at": job.created_at,
        }
        for job in action_jobs
    ]
    jobs.extend(
        {
            "title": "Bulk upload",
            "status": job.status,
            "user": job.requested_by.email,
            "created_at": job.created_at,
        }
        for job in upload_jobs
    )
    return sorted(jobs, key=lambda item: item["created_at"], reverse=True)[:5]


def _recent_datasets():
    from djapps.datasets.models import Dataset

    return (
        Dataset.objects.select_related("publisher_user", "category")
        .order_by("-created_at")[:5]
    )


def _recent_tisp_cache():
    from djapps.tisp.models import TispApiResponseCache

    return TispApiResponseCache.objects.order_by("-fetched_at")[:5]


def _format_count(value):
    return f"{value:,}"
