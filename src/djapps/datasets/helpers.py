from django.db.models import Q
from rest_framework.exceptions import ValidationError

from djapps.datasets.models import DatasetFile, DatasetStatus, DatasetStatusHistory, FileValidationStatus
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
                metadata_errors[label] = [f"{label.replace('_', ' ').title()} is required."]
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
            errors["files"] = ["At least one validated safe file is required before review."]

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
