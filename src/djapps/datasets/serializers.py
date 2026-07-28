import hashlib
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.serializers import ModelSerializer

from djapps.datasets.constants import STRUCTURED_DATA_SUPPORTED_FORMATS
from djapps.datasets.models import (
    Category,
    Dataset,
    DatasetAuditLog,
    DatasetBookmark,
    DatasetBulkActionJob,
    DatasetBulkUploadJob,
    DatasetBulkUploadJobItem,
    DatasetFile,
    DatasetFrequency,
    DatasetMetadata,
    DatasetStatus,
    DatasetStatusHistory,
    DatasetTag,
    DatasetVersion,
    FileValidationStatus,
    IndexingStatus,
    Region,
    Tag,
)

CHARTABLE_DATA_SUPPORTED_FORMATS = set(STRUCTURED_DATA_SUPPORTED_FORMATS) - {"pdf"}


DEFAULT_ALLOWED_DATASET_FILE_EXTENSIONS = {
    ".csv",
    ".json",
    ".pdf",
    ".tsv",
    ".txt",
    ".xls",
    ".xlsx",
    ".xml",
    ".sdmx",
    ".zip",
}
DEFAULT_MAX_DATASET_FILE_SIZE = 50 * 1024 * 1024
DATASET_ADMIN_BULK_ACTION_CHOICES = (
    ("approve", "Approve"),
    ("reject", "Reject"),
    ("publish", "Publish"),
)
DATASET_REVIEW_ACTION_CHOICES = (
    ("approve", "Approve"),
    ("reject", "Reject"),
)
User = get_user_model()


def _compute_file_checksum(uploaded_file):
    checksum = hashlib.sha256()
    current_position = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None

    for chunk in uploaded_file.chunks():
        checksum.update(chunk)

    if current_position is not None:
        uploaded_file.seek(current_position)

    return checksum.hexdigest()


def get_dataset_file_validation_config():
    allowed_extensions = set(
        getattr(
            settings,
            "DATASET_ALLOWED_FILE_EXTENSIONS",
            DEFAULT_ALLOWED_DATASET_FILE_EXTENSIONS,
        )
    )
    max_size = getattr(
        settings,
        "DATASET_MAX_UPLOAD_SIZE",
        DEFAULT_MAX_DATASET_FILE_SIZE,
    )
    return allowed_extensions, max_size


def inspect_dataset_file(uploaded_file, *, original_name=None, file_size=None):
    filename = original_name or getattr(uploaded_file, "name", "")
    extension = os.path.splitext(filename)[1].lower()
    allowed_extensions, max_size = get_dataset_file_validation_config()

    errors = []
    resolved_file_size = file_size
    if resolved_file_size is None:
        try:
            resolved_file_size = uploaded_file.size
        except (AttributeError, FileNotFoundError, OSError, ValueError):
            errors.append("File could not be read from storage.")

    if extension not in allowed_extensions:
        errors.append("Unsupported file type.")

    if resolved_file_size is not None and resolved_file_size > max_size:
        errors.append("File exceeds the maximum allowed size.")

    checksum = ""
    try:
        checksum = _compute_file_checksum(uploaded_file)
    except (AttributeError, FileNotFoundError, OSError, ValueError):
        if "File could not be read from storage." not in errors:
            errors.append("File could not be read from storage.")

    return {
        "filename": filename,
        "file_size": resolved_file_size,
        "file_format": extension.lstrip("."),
        "checksum": checksum,
        "errors": errors,
    }


class CategorySerializer(ModelSerializer):
    class Meta:
        model = Category
        fields = (
            "id",
            "name",
            "slug",
        )
        extra_kwargs = {
            "slug": {"required": False},
        }


class TagSerializer(ModelSerializer):
    class Meta:
        model = Tag
        fields = (
            "id",
            "name",
            "slug",
        )
        extra_kwargs = {
            "slug": {"required": False},
        }


class DatasetMetadataSummarySerializer(ModelSerializer):
    class Meta:
        model = DatasetMetadata
        fields = (
            "id",
            "title",
            "description",
            "license",
            "frequency",
            "region",
            "year",
            "publisher_name",
        )


class DatasetFileSummarySerializer(ModelSerializer):
    class Meta:
        model = DatasetFile
        fields = (
            "id",
            "filename",
            "file_size",
            "file_format",
            "checksum",
            "is_primary",
            "validation_status",
            "validated_at",
            "validation_notes",
            "is_safe",
        )


class DatasetVersionSummarySerializer(ModelSerializer):
    files = DatasetFileSummarySerializer(many=True, read_only=True)

    class Meta:
        model = DatasetVersion
        fields = (
            "id",
            "version_number",
            "changelog",
            "created_by",
            "files",
        )


class DatasetSerializer(ModelSerializer):
    publisher_user_id = serializers.UUIDField(read_only=True)
    category = CategorySerializer(read_only=True)

    class Meta:
        model = Dataset
        fields = (
            "id",
            "category",
            "publisher_user_id",
            "slug",
            "status",
            "visibility",
            "published_at",
        )


class DatasetAdminQueueItemSerializer(ModelSerializer):
    title = serializers.CharField(read_only=True, allow_null=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    has_metadata = serializers.BooleanField(read_only=True)
    has_tag = serializers.BooleanField(read_only=True)
    has_file = serializers.BooleanField(read_only=True)
    primary_file_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Dataset
        fields = (
            "id",
            "slug",
            "title",
            "status",
            "visibility",
            "category_slug",
            "category_name",
            "has_metadata",
            "has_tag",
            "has_file",
            "primary_file_id",
            "updated_at",
            "created_at",
        )


class DatasetAdminQueueSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField(read_only=True)
    draft = serializers.IntegerField(read_only=True)
    in_review = serializers.IntegerField(read_only=True)
    approved = serializers.IntegerField(read_only=True)
    rejected = serializers.IntegerField(read_only=True)
    published = serializers.IntegerField(read_only=True)


class DatasetAdminBulkActionSerializer(serializers.Serializer):
    ACTION_APPROVE = "approve"
    ACTION_REJECT = "reject"
    ACTION_PUBLISH = "publish"

    ACTION_CHOICES = DATASET_ADMIN_BULK_ACTION_CHOICES

    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    dataset_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=100,
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate_dataset_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Duplicate dataset IDs are not allowed.")
        return value

    def validate(self, attrs):
        if attrs["action"] == self.ACTION_REJECT and not attrs.get("reason"):
            raise serializers.ValidationError(
                {"reason": ["This field is required when rejecting datasets."]}
            )
        return attrs


class DatasetAdminBulkActionProcessedSerializer(serializers.Serializer):
    dataset_id = serializers.UUIDField(read_only=True)
    status = serializers.ChoiceField(choices=DatasetStatus.CHOICES, read_only=True)


class DatasetAdminBulkActionFailureSerializer(serializers.Serializer):
    dataset_id = serializers.UUIDField(read_only=True)
    error = serializers.CharField(read_only=True)


class DatasetAdminBulkActionResponseSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=DatasetAdminBulkActionSerializer.ACTION_CHOICES,
        read_only=True,
    )
    requested_count = serializers.IntegerField(read_only=True)
    processed_count = serializers.IntegerField(read_only=True)
    failed_count = serializers.IntegerField(read_only=True)
    processed = DatasetAdminBulkActionProcessedSerializer(many=True, read_only=True)
    failed = DatasetAdminBulkActionFailureSerializer(many=True, read_only=True)


class DatasetAdminBulkActionJobSerializer(ModelSerializer):
    requested_by_email = serializers.EmailField(source="requested_by.email", read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = DatasetBulkActionJob
        fields = (
            "id",
            "action",
            "status",
            "requested_by_email",
            "requested_count",
            "processed_count",
            "failed_count",
            "task_id",
            "error",
            "created_at",
            "started_at",
            "completed_at",
        )


class DatasetAdminBulkActionJobDetailSerializer(DatasetAdminBulkActionJobSerializer):
    requested_by_id = serializers.UUIDField(source="requested_by.id", read_only=True)
    dataset_ids = serializers.ListField(child=serializers.CharField(), read_only=True)
    reason = serializers.CharField(read_only=True)
    audit_context = serializers.JSONField(read_only=True)
    processed = serializers.JSONField(read_only=True)
    failed = serializers.JSONField(read_only=True)

    class Meta(DatasetAdminBulkActionJobSerializer.Meta):
        fields = DatasetAdminBulkActionJobSerializer.Meta.fields + (
            "requested_by_id",
            "dataset_ids",
            "reason",
            "audit_context",
            "processed",
            "failed",
        )


class DatasetBulkUploadItemInputSerializer(serializers.Serializer):
    dataset_id = serializers.UUIDField()
    dataset_version_id = serializers.UUIDField(required=False, allow_null=True)
    is_primary = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        if attrs.get("dataset_version_id") is None:
            attrs.pop("dataset_version_id", None)
        return attrs


class DatasetBulkUploadJobCreateSerializer(serializers.Serializer):
    items = DatasetBulkUploadItemInputSerializer(many=True)
    publish_after_upload = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one upload item is required.")
        dataset_ids = [str(item["dataset_id"]) for item in value]
        if len(set(dataset_ids)) != len(dataset_ids):
            raise serializers.ValidationError("Duplicate dataset IDs are not allowed.")
        return value


class DatasetBulkUploadJobItemSerializer(ModelSerializer):
    dataset_id = serializers.UUIDField(source="dataset.id", read_only=True)
    dataset_slug = serializers.CharField(source="dataset.slug", read_only=True)
    dataset_version_id = serializers.UUIDField(source="dataset_version.id", read_only=True)
    status = serializers.CharField(read_only=True)
    result = serializers.JSONField(read_only=True)

    class Meta:
        model = DatasetBulkUploadJobItem
        fields = (
            "id",
            "dataset_id",
            "dataset_slug",
            "dataset_version_id",
            "filename",
            "is_primary",
            "status",
            "result",
            "error",
            "created_at",
            "processed_at",
        )


class DatasetBulkUploadJobSerializer(ModelSerializer):
    requested_by_email = serializers.EmailField(source="requested_by.email", read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = DatasetBulkUploadJob
        fields = (
            "id",
            "status",
            "publish_after_upload",
            "reason",
            "requested_by_email",
            "total_count",
            "processed_count",
            "failed_count",
            "task_id",
            "error",
            "created_at",
            "started_at",
            "completed_at",
        )


class DatasetBulkUploadJobDetailSerializer(DatasetBulkUploadJobSerializer):
    requested_by_id = serializers.UUIDField(source="requested_by.id", read_only=True)
    items = DatasetBulkUploadJobItemSerializer(many=True, read_only=True)

    class Meta(DatasetBulkUploadJobSerializer.Meta):
        fields = DatasetBulkUploadJobSerializer.Meta.fields + (
            "requested_by_id",
            "items",
        )

class DatasetPaginationMetaSerializer(serializers.Serializer):
    page = serializers.IntegerField(read_only=True)
    page_size = serializers.IntegerField(read_only=True)
    total_pages = serializers.IntegerField(read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    has_next = serializers.BooleanField(read_only=True)
    has_previous = serializers.BooleanField(read_only=True)
    next = serializers.CharField(read_only=True, allow_null=True)
    previous = serializers.CharField(read_only=True, allow_null=True)


class DatasetAdminBulkActionJobListPayloadSerializer(serializers.Serializer):
    items = DatasetAdminBulkActionJobSerializer(many=True, read_only=True)
    pagination = DatasetPaginationMetaSerializer(read_only=True)


class DatasetBulkUploadJobListPayloadSerializer(serializers.Serializer):
    items = DatasetBulkUploadJobSerializer(many=True, read_only=True)
    pagination = DatasetPaginationMetaSerializer(read_only=True)


class DatasetDetailSerializer(DatasetSerializer):
    metadata = DatasetMetadataSummarySerializer(many=True, read_only=True)
    tags = serializers.SerializerMethodField()
    versions = DatasetVersionSummarySerializer(many=True, read_only=True)

    class Meta(DatasetSerializer.Meta):
        fields = DatasetSerializer.Meta.fields + (
            "metadata",
            "tags",
            "versions",
        )

    @extend_schema_field(TagSerializer(many=True))
    def get_tags(self, obj):
        return TagSerializer([item.tag for item in obj.dataset_tags.select_related("tag").all()], many=True).data


class DatasetBookmarkSerializer(ModelSerializer):
    dataset = DatasetDetailSerializer(read_only=True)

    class Meta:
        model = DatasetBookmark
        fields = (
            "id",
            "dataset",
            "created_at",
        )


class DatasetBookmarkListPayloadSerializer(serializers.Serializer):
    items = DatasetBookmarkSerializer(many=True, read_only=True)
    pagination = DatasetPaginationMetaSerializer(read_only=True)


class DatasetWriteSerializer(ModelSerializer):
    publisher_user_id = serializers.UUIDField(read_only=True)
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())

    class Meta:
        model = Dataset
        fields = (
            "id",
            "category",
            "publisher_user_id",
            "slug",
            "status",
            "visibility",
            "published_at",
        )
        read_only_fields = (
            "id",
            "publisher_user_id",
            "status",
            "visibility",
            "published_at",
        )
        extra_kwargs = {
            "slug": {"required": False},
        }


class DatasetSubmitReviewSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class DatasetReviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=DATASET_REVIEW_ACTION_CHOICES)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        if attrs["action"] == "reject" and not attrs.get("reason"):
            raise serializers.ValidationError(
                {"reason": ["This field is required when rejecting a dataset."]}
            )
        return attrs


class DatasetPublishSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class DatasetRestoreSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class DatasetTransferOwnerSerializer(serializers.Serializer):
    new_owner_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
        ),
        source="new_owner",
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate_new_owner_id(self, value):
        if not value.has_perm("datasets.change_dataset"):
            raise serializers.ValidationError(
                "Selected user must have dataset management permission."
            )
        return value

    def validate(self, attrs):
        dataset = self.context.get("dataset")
        new_owner = attrs["new_owner"]
        if dataset is not None and dataset.publisher_user_id == new_owner.id:
            raise serializers.ValidationError(
                {"new_owner_id": ["The selected user already owns this dataset."]}
            )
        return attrs


class DatasetVersionSerializer(ModelSerializer):
    dataset = DatasetSerializer(read_only=True)
    dataset_id = serializers.PrimaryKeyRelatedField(queryset=Dataset.objects.all(), source="dataset")

    class Meta:
        model = DatasetVersion
        fields = (
            "id",
            "dataset",
            "dataset_id",
            "created_by",
            "version_number",
            "changelog",
        )
        read_only_fields = (
            "id",
            "created_by",
        )

    def validate(self, attrs):
        dataset = attrs.get("dataset") or getattr(self.instance, "dataset", None)
        version_number = attrs.get("version_number") or getattr(self.instance, "version_number", None)

        if dataset and version_number:
            existing = DatasetVersion.objects.filter(dataset=dataset, version_number=version_number)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    {"version_number": ["This version already exists for the dataset."]}
                )
        return attrs


class DatasetFileSerializer(ModelSerializer):
    dataset_version = DatasetVersionSerializer(read_only=True)
    dataset_version_id = serializers.PrimaryKeyRelatedField(
        queryset=DatasetVersion.objects.all(),
        source="dataset_version",
        required=False,
        allow_null=True,
    )
    dataset_id = serializers.PrimaryKeyRelatedField(
        queryset=Dataset.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    chart_url = serializers.SerializerMethodField()
    chart_available = serializers.SerializerMethodField()

    class Meta:
        model = DatasetFile
        fields = (
            "id",
            "dataset_version",
            "dataset_version_id",
            "dataset_id",
            "uploaded_by",
            "file",
            "filename",
            "file_size",
            "file_format",
            "checksum",
            "is_primary",
            "validation_status",
            "validated_at",
            "validation_notes",
            "is_safe",
            "chart_url",
            "chart_available",
        )
        read_only_fields = (
            "id",
            "uploaded_by",
            "filename",
            "file_size",
            "file_format",
            "checksum",
            "validation_status",
            "validated_at",
            "validation_notes",
            "is_safe",
            "chart_url",
            "chart_available",
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        dataset = attrs.get("dataset_id")
        dataset_version = attrs.get("dataset_version")

        if self.instance is None and not dataset and not dataset_version:
            raise serializers.ValidationError(
                {"dataset_version_id": ["Provide dataset_version_id or dataset_id."]}
            )

        if dataset and dataset_version and dataset_version.dataset_id != dataset.id:
            raise serializers.ValidationError(
                {"dataset_version_id": ["The provided version does not belong to dataset_id."]}
            )

        if attrs.get("is_primary") and dataset_version:
            existing = DatasetFile.objects.filter(
                dataset_version=dataset_version,
                is_primary=True,
            )
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    {"is_primary": ["Only one primary file is allowed per dataset version."]}
                )

        return attrs

    def validate_file(self, uploaded_file):
        inspection = inspect_dataset_file(uploaded_file)
        if inspection["errors"]:
            raise serializers.ValidationError(" ".join(inspection["errors"]))

        return uploaded_file

    def _resolve_dataset_version(self, validated_data):
        dataset_version = validated_data.get("dataset_version")
        if dataset_version is not None:
            return dataset_version

        dataset = validated_data.pop("dataset_id", None)
        if dataset is None:
            return None

        dataset_version = dataset.versions.order_by("created_at").first()
        if dataset_version is not None:
            return dataset_version

        request = self.context.get("request")
        user = getattr(request, "user", None)
        return DatasetVersion.objects.create(
            dataset=dataset,
            created_by=user,
            version_number="1.0",
            changelog="Initial version auto-created for first file upload.",
        )

    def _populate_file_metadata(self, validated_data):
        uploaded_file = validated_data.get("file")
        if uploaded_file is None:
            return

        inspection = inspect_dataset_file(uploaded_file)
        validated_data["filename"] = inspection["filename"]
        validated_data["file_size"] = inspection["file_size"]
        validated_data["file_format"] = inspection["file_format"]
        validated_data["checksum"] = inspection["checksum"]
        is_valid = not inspection["errors"]
        validated_data["validation_status"] = (
            FileValidationStatus.VALIDATED if is_valid else FileValidationStatus.REJECTED
        )
        validated_data["validated_at"] = timezone.now()
        validated_data["validation_notes"] = (
            "Automatic validation passed."
            if is_valid
            else " ".join(inspection["errors"])
        )
        validated_data["is_safe"] = is_valid

    def create(self, validated_data):
        dataset_version = self._resolve_dataset_version(validated_data)
        if dataset_version is not None:
            validated_data["dataset_version"] = dataset_version
        self._populate_file_metadata(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("dataset_id", None)
        self._populate_file_metadata(validated_data)
        return super().update(instance, validated_data)

    def _has_chart_access(self, obj):
        return (
            obj.validation_status == FileValidationStatus.VALIDATED
            and obj.is_safe
            and (obj.file_format or "").lower() in CHARTABLE_DATA_SUPPORTED_FORMATS
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_chart_url(self, obj):
        if not self._has_chart_access(obj):
            return None
        chart_url = reverse("dataset-file-chart", kwargs={"pk": obj.pk})
        request = self.context.get("request")
        return request.build_absolute_uri(chart_url) if request is not None else chart_url

    @extend_schema_field(serializers.BooleanField())
    def get_chart_available(self, obj):
        return self._has_chart_access(obj)


class DatasetFileDataQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, min_value=1, max_value=200, default=50)
    offset = serializers.IntegerField(required=False, min_value=0, default=0)


class DatasetFileValidateSerializer(serializers.Serializer):
    validation_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
    )


class DatasetFileDataResponseSerializer(serializers.Serializer):
    file_id = serializers.UUIDField(read_only=True)
    filename = serializers.CharField(read_only=True)
    file_format = serializers.CharField(read_only=True)
    structure_type = serializers.CharField(read_only=True)
    columns = serializers.ListField(child=serializers.CharField(), read_only=True, required=False)
    rows = serializers.ListField(
        child=serializers.DictField(child=serializers.JSONField()),
        read_only=True,
        required=False,
    )
    data = serializers.JSONField(read_only=True, required=False)
    sdmx = serializers.JSONField(read_only=True, required=False)
    document = serializers.JSONField(read_only=True, required=False)
    offset = serializers.IntegerField(read_only=True)
    limit = serializers.IntegerField(read_only=True)
    returned_items = serializers.IntegerField(read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    returned_rows = serializers.IntegerField(read_only=True)
    total_rows = serializers.IntegerField(read_only=True)
    has_more = serializers.BooleanField(read_only=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True, required=False)


class DatasetFileChartQuerySerializer(serializers.Serializer):
    chart_type = serializers.ChoiceField(
        choices=("bar", "pie", "line", "scatter"),
        required=False,
        default="bar",
    )
    x_field = serializers.CharField(required=False, allow_blank=False)
    y_field = serializers.CharField(required=False, allow_blank=False)
    group_by = serializers.CharField(required=False, allow_blank=False)
    metric = serializers.ChoiceField(
        choices=("count", "sum", "avg", "min", "max"),
        required=False,
        default="count",
    )
    sort = serializers.ChoiceField(
        choices=("asc", "desc"),
        required=False,
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)

    def validate(self, attrs):
        chart_type = attrs.get("chart_type", "bar")
        x_field = attrs.get("x_field")
        y_field = attrs.get("y_field")
        group_by = attrs.get("group_by")
        metric = attrs.get("metric", "count")

        if chart_type == "scatter":
            if not x_field or not y_field:
                raise serializers.ValidationError(
                    {"detail": ["Scatter charts require both x_field and y_field."]}
                )
            return attrs

        if not (group_by or x_field):
            raise serializers.ValidationError(
                {"x_field": ["This field is required for bar, pie, and line charts."]}
            )

        if metric != "count" and not y_field:
            raise serializers.ValidationError(
                {"y_field": ["This field is required when using sum, avg, min, or max metrics."]}
            )
        return attrs


class DatasetChartPointSerializer(serializers.Serializer):
    label = serializers.CharField(read_only=True, allow_null=True, required=False)
    x = serializers.JSONField(read_only=True, allow_null=True, required=False)
    y = serializers.JSONField(read_only=True, allow_null=True, required=False)
    value = serializers.JSONField(read_only=True, allow_null=True, required=False)
    count = serializers.IntegerField(read_only=True)


class DatasetChartSeriesSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    field = serializers.CharField(read_only=True, allow_null=True, required=False)
    points = DatasetChartPointSerializer(many=True, read_only=True)


class DatasetFileChartResponseSerializer(serializers.Serializer):
    file_id = serializers.UUIDField(read_only=True)
    filename = serializers.CharField(read_only=True)
    file_format = serializers.CharField(read_only=True)
    structure_type = serializers.CharField(read_only=True)
    chart_type = serializers.CharField(read_only=True)
    x_field = serializers.CharField(read_only=True, allow_null=True, required=False)
    y_field = serializers.CharField(read_only=True, allow_null=True, required=False)
    group_by = serializers.CharField(read_only=True, allow_null=True, required=False)
    metric = serializers.CharField(read_only=True)
    columns = serializers.ListField(child=serializers.CharField(), read_only=True)
    point_count = serializers.IntegerField(read_only=True)
    source_row_count = serializers.IntegerField(read_only=True)
    series = DatasetChartSeriesSerializer(many=True, read_only=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True, required=False)


class DatasetTagSerializer(ModelSerializer):
    dataset = DatasetSerializer(read_only=True)
    dataset_id = serializers.PrimaryKeyRelatedField(queryset=Dataset.objects.all(), source="dataset")
    tag = TagSerializer(read_only=True)
    tag_id = serializers.PrimaryKeyRelatedField(queryset=Tag.objects.all(), source="tag")

    class Meta:
        model = DatasetTag
        fields = (
            "id",
            "dataset",
            "dataset_id",
            "tag",
            "tag_id",
        )

    def validate(self, attrs):
        dataset = attrs.get("dataset") or getattr(self.instance, "dataset", None)
        tag = attrs.get("tag") or getattr(self.instance, "tag", None)
        if dataset and tag:
            existing = DatasetTag.objects.filter(dataset=dataset, tag=tag)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    {"tag_id": ["This tag is already linked to the dataset."]}
                )
        return attrs


class DatasetMetadataSerializer(ModelSerializer):
    dataset = DatasetSerializer(read_only=True)
    dataset_id = serializers.PrimaryKeyRelatedField(queryset=Dataset.objects.all(), source="dataset")
    frequency = serializers.ChoiceField(choices=DatasetFrequency.CHOICES)
    publisher_name = serializers.CharField(read_only=True)

    class Meta:
        model = DatasetMetadata
        fields = (
            "id",
            "dataset",
            "dataset_id",
            "title",
            "description",
            "license",
            "frequency",
            "region",
            "year",
            "publisher_name",
        )

    def validate_year(self, value):
        if value is None:
            return value

        current_year = timezone.now().year + 1
        if value < 1900 or value > current_year:
            raise serializers.ValidationError("Enter a valid year.")
        return value

    def validate(self, attrs):
        dataset = attrs.get("dataset") or getattr(self.instance, "dataset", None)
        if dataset is not None and self.instance is None:
            if DatasetMetadata.objects.filter(dataset=dataset).exists():
                raise serializers.ValidationError(
                    {"dataset_id": ["This dataset already has metadata."]}
                )
        return attrs


class IndexingStatusSerializer(ModelSerializer):
    dataset = DatasetSerializer(read_only=True)
    dataset_id = serializers.PrimaryKeyRelatedField(queryset=Dataset.objects.all(), source="dataset")

    class Meta:
        model = IndexingStatus
        fields = (
            "id",
            "dataset",
            "dataset_id",
            "indexed_at",
            "status",
            "details",
        )


class DatasetStatusHistorySerializer(ModelSerializer):
    dataset = DatasetSerializer(read_only=True)
    dataset_id = serializers.PrimaryKeyRelatedField(queryset=Dataset.objects.all(), source="dataset", write_only=True)

    class Meta:
        model = DatasetStatusHistory
        fields = (
            "id",
            "dataset",
            "dataset_id",
            "changed_by",
            "old_status",
            "new_status",
            "reason",
            "changed_at",
        )
        read_only_fields = (
            "id",
            "changed_by",
            "changed_at",
        )


class DatasetAuditLogSerializer(ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True)

    class Meta:
        model = DatasetAuditLog
        fields = (
            "id",
            "dataset",
            "actor",
            "actor_email",
            "action",
            "target_model",
            "target_id",
            "details",
            "created_at",
        )
        read_only_fields = fields

class RegionSerializer(ModelSerializer):
    class Meta:
        model = Region
        fields = (
            "id",
            "name"
        )
