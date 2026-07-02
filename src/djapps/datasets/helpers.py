from django.utils import timezone
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from djapps.datasets.audit import log_dataset_event
from djapps.datasets.models import (
    DatasetFile,
    DatasetStatus,
    DatasetStatusHistory,
    FileValidationStatus,
)
from djapps.datasets.permissions import has_dataset_admin_access


def request_audit_details(request, **extra):
    details = {
        "request_id": getattr(request, "request_id", None),
        "ip_address": request.META.get("REMOTE_ADDR"),
        "user_agent": request.META.get("HTTP_USER_AGENT"),
    }
    details.update(extra)
    return {
        key: value
        for key, value in details.items()
        if value is not None and value != ""
    }


def create_status_history(dataset, changed_by, old_status, new_status, reason):
    return DatasetStatusHistory.objects.create(
        dataset=dataset,
        changed_by=changed_by,
        old_status=old_status,
        new_status=new_status,
        reason=reason,
    )


def format_validation_error(exc):
    if isinstance(exc.detail, list):
        return " ".join(str(item) for item in exc.detail)
    if isinstance(exc.detail, dict):
        return str(exc.detail)
    return str(exc.detail)


def process_dataset_bulk_action(
    dataset,
    *,
    action,
    reason,
    actor,
    audit_details=None,
):
    old_status = dataset.status

    if action == "approve":
        if dataset.status != DatasetStatus.IN_REVIEW:
            raise ValidationError("Only datasets in review can be approved.")
        dataset.status = DatasetStatus.APPROVED
        final_reason = reason or "Dataset approved for publication."
        audit_action = "dataset_review_approved"
        update_fields = ["status", "visibility", "updated_at"]
    elif action == "reject":
        if dataset.status != DatasetStatus.IN_REVIEW:
            raise ValidationError("Only datasets in review can be rejected.")
        dataset.status = DatasetStatus.REJECTED
        dataset.visibility = False
        final_reason = reason
        audit_action = "dataset_review_rejected"
        update_fields = ["status", "visibility", "updated_at"]
    elif action == "publish":
        if dataset.status != DatasetStatus.APPROVED:
            raise ValidationError("Only approved datasets can be published.")
        dataset.status = DatasetStatus.PUBLISHED
        dataset.visibility = True
        dataset.published_at = dataset.published_at or timezone.now()
        final_reason = reason or "Published via API."
        audit_action = "dataset_published"
        update_fields = ["status", "visibility", "published_at", "updated_at"]
    else:
        raise ValidationError({"action": ["Unsupported bulk action."]})

    dataset.save(update_fields=update_fields)
    create_status_history(dataset, actor, old_status, dataset.status, final_reason)
    log_dataset_event(
        dataset,
        audit_action,
        actor=actor,
        details={
            **(audit_details or {}),
            "old_status": old_status,
            "new_status": dataset.status,
            "reason": final_reason,
        },
    )
    return {
        "dataset_id": str(dataset.id),
        "status": dataset.status,
    }


def validate_dataset_ready_for_review(dataset):
    errors = {}
    metadata = dataset.metadata.first()

    if metadata is None:
        errors["metadata"] = ["Dataset metadata is required before review."]
    else:
        metadata_errors = {}
        for field_name, label in (
            ("title", "title"),
            ("description", "description"),
            ("license", "license"),
            ("frequency", "frequency"),
            ("region", "region"),
            ("year", "year"),
        ):
            value = getattr(metadata, field_name)
            if value in {None, ""}:
                metadata_errors[label] = [
                    f"{label.replace('_', ' ').title()} is required."
                ]
        if metadata_errors:
            errors["metadata"] = metadata_errors

    if not dataset.dataset_tags.exists():
        errors["tags"] = ["At least one tag is required before review."]

    versions = dataset.versions.prefetch_related("files").all()
    if not versions.exists():
        errors["versions"] = ["At least one dataset version is required before review."]
    else:
        files = DatasetFile.objects.filter(dataset_version__dataset=dataset)
        if not files.exists():
            errors["files"] = ["At least one dataset file is required before review."]
        elif not files.filter(
            validation_status=FileValidationStatus.VALIDATED,
            is_safe=True,
        ).exists():
            errors["files"] = [
                "At least one validated safe file is required before review."
            ]

    if errors:
        raise ValidationError(errors)


def filter_related_queryset_by_dataset_access(queryset, user, dataset_lookup):
    active_filter = Q(**{f"{dataset_lookup}__deleted_at__isnull": True})
    public_filter = Q(
        **{
            f"{dataset_lookup}__visibility": True,
            f"{dataset_lookup}__status": DatasetStatus.PUBLISHED,
        }
    )

    if not user or not user.is_authenticated:
        return queryset.filter(active_filter & public_filter)

    if has_dataset_admin_access(user):
        return queryset.filter(active_filter)

    owner_filter = Q(**{f"{dataset_lookup}__publisher_user": user})
    return queryset.filter(active_filter & (public_filter | owner_filter)).distinct()
