from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone
from celery import shared_task
from rest_framework.exceptions import ValidationError

from djapps.datasets.helpers import format_validation_error, process_dataset_bulk_action
from djapps.datasets.models import (
    Dataset,
    DatasetBulkActionJob,
    DatasetBulkActionJobStatus,
    DatasetBulkUploadJob,
    DatasetBulkUploadJobStatus,
)
from djapps.datasets.serializers import DatasetFileSerializer

@shared_task(name="datasets.bulk_action_probe")
def bulk_action_probe(*, action, dataset_ids):
    return {
        "action": action,
        "dataset_count": len(dataset_ids),
    }


@shared_task(bind=True, name="datasets.run_bulk_action_job")
def run_bulk_action_job(self, job_id):
    job = DatasetBulkActionJob.objects.select_related("requested_by").get(pk=job_id)
    if job.status == DatasetBulkActionJobStatus.COMPLETED:
        return {
            "job_id": str(job.id),
            "status": job.status,
        }

    job.status = DatasetBulkActionJobStatus.RUNNING
    job.started_at = job.started_at or timezone.now()
    job.task_id = self.request.id or job.task_id
    job.error = ""
    job.save(update_fields=["status", "started_at", "task_id", "error", "updated_at"])

    dataset_ids = job.dataset_ids or []
    datasets = Dataset.all_objects.filter(id__in=dataset_ids)
    dataset_map = {str(dataset.id): dataset for dataset in datasets}

    processed = []
    failed = []

    try:
        for dataset_id in dataset_ids:
            dataset = dataset_map.get(str(dataset_id))
            if dataset is None:
                failed.append(
                    {
                        "dataset_id": str(dataset_id),
                        "error": "Dataset not found.",
                    }
                )
                continue

            try:
                with transaction.atomic():
                    processed.append(
                        process_dataset_bulk_action(
                            dataset,
                            action=job.action,
                            reason=job.reason,
                            actor=job.requested_by,
                            audit_details=job.audit_context,
                        )
                    )
            except ValidationError as exc:
                failed.append(
                    {
                        "dataset_id": str(dataset.id),
                        "error": format_validation_error(exc),
                    }
                )

        job.status = DatasetBulkActionJobStatus.COMPLETED
        job.processed = processed
        job.failed = failed
        job.processed_count = len(processed)
        job.failed_count = len(failed)
        job.completed_at = timezone.now()
        job.save(
            update_fields=[
                "status",
                "processed",
                "failed",
                "processed_count",
                "failed_count",
                "completed_at",
                "updated_at",
            ]
        )
    except Exception as exc:
        job.status = DatasetBulkActionJobStatus.FAILED
        job.error = str(exc)
        job.completed_at = timezone.now()
        job.save(
            update_fields=["status", "error", "completed_at", "updated_at"]
        )
        raise

    return {
        "job_id": str(job.id),
        "status": job.status,
        "processed_count": job.processed_count,
        "failed_count": job.failed_count,
    }


@shared_task(bind=True, name="datasets.run_bulk_upload_job")
def run_bulk_upload_job(self, job_id):
    job = (
        DatasetBulkUploadJob.objects.select_related("requested_by")
        .prefetch_related("items__dataset", "items__dataset_version")
        .get(pk=job_id)
    )
    if job.status == DatasetBulkUploadJobStatus.COMPLETED:
        return {
            "job_id": str(job.id),
            "status": job.status,
        }

    job.status = DatasetBulkUploadJobStatus.RUNNING
    job.started_at = job.started_at or timezone.now()
    job.task_id = self.request.id or job.task_id
    job.error = ""
    job.save(update_fields=["status", "started_at", "task_id", "error", "updated_at"])

    request = SimpleNamespace(user=job.requested_by)
    processed = []
    failed = []

    try:
        for item in job.items.select_related("dataset", "dataset_version").order_by("created_at", "id"):
            item.status = DatasetBulkUploadJobStatus.RUNNING
            item.error = ""
            item.save(update_fields=["status", "error", "updated_at"])

            try:
                serializer = DatasetFileSerializer(
                    data={
                        "dataset_id": str(item.dataset_id),
                        "dataset_version_id": (
                            str(item.dataset_version_id) if item.dataset_version_id else None
                        ),
                        "file": item.uploaded_file,
                        "is_primary": item.is_primary,
                    },
                    context={"request": request},
                )
                serializer.is_valid(raise_exception=True)
                dataset_file = serializer.save(uploaded_by=job.requested_by)

                publish_result = None
                if job.publish_after_upload:
                    publish_result = process_dataset_bulk_action(
                        item.dataset,
                        action="publish",
                        reason=job.reason or "Published after bulk upload.",
                        actor=job.requested_by,
                        audit_details=job.audit_context,
                    )

                result_payload = {
                    "dataset_id": str(item.dataset_id),
                    "dataset_file_id": str(dataset_file.id),
                    "status": DatasetBulkUploadJobStatus.COMPLETED,
                    "error": "",
                }
                if publish_result is not None:
                    result_payload["publish_result"] = publish_result

                item.dataset_file = dataset_file
                item.result = result_payload
                item.status = DatasetBulkUploadJobStatus.COMPLETED
                item.processed_at = timezone.now()
                item.save(
                    update_fields=[
                        "dataset_file",
                        "result",
                        "status",
                        "processed_at",
                        "updated_at",
                    ]
                )
                processed.append(result_payload)
            except Exception as exc:
                error_message = format_validation_error(exc) if isinstance(exc, ValidationError) else str(exc)
                item.error = error_message
                item.result = {
                    "dataset_id": str(item.dataset_id),
                    "dataset_file_id": None,
                    "status": DatasetBulkUploadJobStatus.FAILED,
                    "error": error_message,
                }
                item.status = DatasetBulkUploadJobStatus.FAILED
                item.processed_at = timezone.now()
                item.save(
                    update_fields=[
                        "error",
                        "result",
                        "status",
                        "processed_at",
                        "updated_at",
                    ]
                )
                failed.append(item.result)

        job.status = DatasetBulkUploadJobStatus.COMPLETED
        job.processed_count = len(processed)
        job.failed_count = len(failed)
        job.completed_at = timezone.now()
        job.save(
            update_fields=[
                "status",
                "processed_count",
                "failed_count",
                "completed_at",
                "updated_at",
            ]
        )
    except Exception as exc:
        job.status = DatasetBulkUploadJobStatus.FAILED
        job.error = str(exc)
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "error", "completed_at", "updated_at"])
        raise

    return {
        "job_id": str(job.id),
        "status": job.status,
        "processed_count": job.processed_count,
        "failed_count": job.failed_count,
    }
