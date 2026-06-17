from rest_framework.permissions import SAFE_METHODS, BasePermission

from djapps.datasets.models import DatasetStatus


def is_owner(user, dataset):
    return bool(user and user.is_authenticated and dataset.publisher_user_id == user.id)


def is_dataset_deleted(dataset):
    return bool(getattr(dataset, "deleted_at", None))


def has_dataset_admin_access(user):
    return bool(
        user
        and user.is_authenticated
        and user.has_perm("datasets.view_all_dataset")
        and user.has_perm("datasets.review_dataset")
    )


def can_view_dataset_audit(user, dataset):
    if is_dataset_deleted(dataset):
        return False
    return bool(
        user
        and user.is_authenticated
        and (has_dataset_admin_access(user) or is_owner(user, dataset))
    )


def can_view_dataset(user, dataset):
    if is_dataset_deleted(dataset):
        return False

    if dataset.visibility and dataset.status == "published":
        return True

    return bool(
        user
        and user.is_authenticated
        and (has_dataset_admin_access(user) or is_owner(user, dataset))
    )


def can_change_dataset(user, dataset):
    if is_dataset_deleted(dataset):
        return False
    return bool(
        user
        and user.is_authenticated
        and user.has_perm("datasets.change_dataset")
        and (
            has_dataset_admin_access(user)
            or (is_owner(user, dataset) and dataset.status in {DatasetStatus.DRAFT, DatasetStatus.REJECTED})
        )
    )


def can_delete_dataset(user, dataset):
    if is_dataset_deleted(dataset):
        return False
    return bool(
        user
        and user.is_authenticated
        and user.has_perm("datasets.delete_dataset")
        and (
            has_dataset_admin_access(user)
            or (is_owner(user, dataset) and dataset.status in {DatasetStatus.DRAFT, DatasetStatus.REJECTED})
        )
    )


def can_review_dataset(user):
    return bool(
        user
        and user.is_authenticated
        and user.has_perm("datasets.review_dataset")
    )


def can_publish_dataset(user):
    return bool(
        user
        and user.is_authenticated
        and user.has_perm("datasets.publish_dataset")
        and user.has_perm("datasets.review_dataset")
    )


def get_dataset_from_object(obj):
    if hasattr(obj, "publisher_user_id"):
        return obj
    if hasattr(obj, "dataset_id"):
        return obj.dataset
    if hasattr(obj, "dataset_version_id"):
        return obj.dataset_version.dataset
    raise AttributeError("Could not resolve dataset from object.")


class CanCreateDataset(BasePermission):
    message = "You do not have permission to create datasets."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.has_perm("datasets.add_dataset")
        )


class CanAccessDataset(BasePermission):
    message = "You do not have permission to access this dataset."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user

        if request.method in SAFE_METHODS:
            return can_view_dataset(user, obj)

        if request.method in {"PUT", "PATCH"}:
            return can_change_dataset(user, obj)

        if request.method == "DELETE":
            return can_delete_dataset(user, obj)

        return False


class CanPublishDataset(BasePermission):
    message = "You do not have permission to publish datasets."

    def has_permission(self, request, view):
        return can_publish_dataset(request.user)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanReviewDataset(BasePermission):
    message = "You do not have permission to review datasets."

    def has_permission(self, request, view):
        return can_review_dataset(request.user)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanViewDatasetAuditLog(BasePermission):
    message = "You do not have permission to access dataset audit logs."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        dataset = get_dataset_from_object(obj)
        return can_view_dataset_audit(request.user, dataset)


class CanAccessDatasetRelatedObject(BasePermission):
    message = "You do not have permission to access this resource."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        dataset = get_dataset_from_object(obj)
        user = request.user

        if request.method in SAFE_METHODS:
            return can_view_dataset(user, dataset)

        if request.method in {"PUT", "PATCH"}:
            return can_change_dataset(user, dataset)

        if request.method == "DELETE":
            return can_delete_dataset(user, dataset)

        return False
