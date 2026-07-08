from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from djapps.datasets.models import Dataset, DatasetFile, DatasetVersion, FileValidationStatus
from djapps.datasets.serializers import CategorySerializer, DatasetMetadataSummarySerializer, TagSerializer
from djapps.gateway.models import APIConsumer, APIKey, APIUsageLog


STRUCTURED_DATA_SUPPORTED_FORMATS = {
    "csv",
    "tsv",
    "json",
    "xlsx",
    "xls",
    "pdf",
    "xml",
    "sdmx",
}
class OpenDatasetFileSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    data_url = serializers.SerializerMethodField()
    data_available = serializers.SerializerMethodField()

    class Meta:
        model = DatasetFile
        fields = (
            "id",
            "filename",
            "file_size",
            "file_format",
            "checksum",
            "is_primary",
            "download_url",
            "data_url",
            "data_available",
        )

    def _build_url(self, route_name, obj):
        route_kwargs = {"pk": obj.pk}
        if route_name in {"gateway-dataset-file-download", "gateway-dataset-file-data"}:
            route_kwargs = {"file_id": obj.pk}
        return reverse(route_name, kwargs=route_kwargs)

    def _has_structured_access(self, obj):
        return (
            obj.validation_status == FileValidationStatus.VALIDATED
            and obj.is_safe
            and obj.file_format.lower() in STRUCTURED_DATA_SUPPORTED_FORMATS
        )

    @extend_schema_field(serializers.CharField())
    def get_download_url(self, obj):
        return self._build_url("gateway-dataset-file-download", obj)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_data_url(self, obj):
        if not self._has_structured_access(obj):
            return None
        return self._build_url("gateway-dataset-file-data", obj)

    @extend_schema_field(serializers.BooleanField())
    def get_data_available(self, obj):
        return self._has_structured_access(obj)


class OpenDatasetVersionSerializer(serializers.ModelSerializer):
    files = serializers.SerializerMethodField()

    class Meta:
        model = DatasetVersion
        fields = (
            "id",
            "version_number",
            "changelog",
            "created_at",
            "files",
        )

    @extend_schema_field(OpenDatasetFileSerializer(many=True))
    def get_files(self, obj):
        public_files = obj.files.filter(
            validation_status=FileValidationStatus.VALIDATED,
            is_safe=True,
        ).order_by("-is_primary", "filename")
        return OpenDatasetFileSerializer(public_files, many=True, context=self.context).data


class OpenDatasetFileListSerializer(OpenDatasetFileSerializer):
    dataset_version_id = serializers.UUIDField(source="dataset_version.id", read_only=True)
    version_number = serializers.CharField(source="dataset_version.version_number", read_only=True)
    version_created_at = serializers.DateTimeField(source="dataset_version.created_at", read_only=True)

    class Meta(OpenDatasetFileSerializer.Meta):
        fields = (
            "id",
            "dataset_version_id",
            "version_number",
            "version_created_at",
            "filename",
            "file_size",
            "file_format",
            "checksum",
            "is_primary",
            "download_url",
            "data_url",
            "data_available",
        )


class OpenDatasetSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    metadata = DatasetMetadataSummarySerializer(many=True, read_only=True)
    tags = serializers.SerializerMethodField()
    versions = serializers.SerializerMethodField()

    class Meta:
        model = Dataset
        fields = (
            "id",
            "slug",
            "category",
            "metadata",
            "tags",
            "versions",
            "published_at",
        )

    @extend_schema_field(TagSerializer(many=True))
    def get_tags(self, obj):
        tags = [item.tag for item in obj.dataset_tags.select_related("tag").all()]
        return TagSerializer(tags, many=True).data

    @extend_schema_field(OpenDatasetVersionSerializer(many=True))
    def get_versions(self, obj):
        versions = obj.versions.order_by("-created_at")
        return OpenDatasetVersionSerializer(versions, many=True, context=self.context).data


class GatewayTagSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    dataset_count = serializers.IntegerField(read_only=True)


class GatewayFacetValueSerializer(serializers.Serializer):
    value = serializers.CharField(read_only=True)
    dataset_count = serializers.IntegerField(read_only=True)


class GatewayYearFacetSerializer(serializers.Serializer):
    value = serializers.IntegerField(read_only=True)
    dataset_count = serializers.IntegerField(read_only=True)


class GatewayFrequencySummarySerializer(serializers.Serializer):
    value = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    dataset_count = serializers.IntegerField(read_only=True)


class GatewayCategorySummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    dataset_count = serializers.IntegerField(read_only=True)


class DatasetFormatSerializer(serializers.Serializer):
    file_format = serializers.CharField(read_only=True)
    dataset_count = serializers.IntegerField(read_only=True)
    file_count = serializers.IntegerField(read_only=True)
    structured_data_supported = serializers.BooleanField(read_only=True)


class GatewayDatasetFacetsSerializer(serializers.Serializer):
    total_datasets = serializers.IntegerField(read_only=True)
    categories = GatewayCategorySummarySerializer(many=True, read_only=True)
    tags = GatewayTagSummarySerializer(many=True, read_only=True)
    licenses = GatewayFacetValueSerializer(many=True, read_only=True)
    publishers = GatewayFacetValueSerializer(many=True, read_only=True)
    frequencies = GatewayFrequencySummarySerializer(many=True, read_only=True)
    regions = GatewayFacetValueSerializer(many=True, read_only=True)
    years = GatewayYearFacetSerializer(many=True, read_only=True)
    formats = DatasetFormatSerializer(many=True, read_only=True)


class GatewayDatasetChangeSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    title = serializers.SerializerMethodField()
    publisher_name = serializers.SerializerMethodField()
    last_changed_at = serializers.DateTimeField(read_only=True)
    latest_version_id = serializers.SerializerMethodField()
    latest_version_number = serializers.SerializerMethodField()

    class Meta:
        model = Dataset
        fields = (
            "id",
            "slug",
            "category",
            "title",
            "publisher_name",
            "published_at",
            "last_changed_at",
            "latest_version_id",
            "latest_version_number",
        )

    def _latest_metadata(self, obj):
        metadata = list(obj.metadata.all())
        return max(metadata, key=lambda item: item.created_at) if metadata else None

    def _latest_version(self, obj):
        versions = list(obj.versions.all())
        return max(versions, key=lambda item: item.created_at) if versions else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_title(self, obj):
        metadata = self._latest_metadata(obj)
        return metadata.title if metadata is not None else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_publisher_name(self, obj):
        metadata = self._latest_metadata(obj)
        return metadata.publisher_name if metadata is not None else None

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_latest_version_id(self, obj):
        version = self._latest_version(obj)
        return version.id if version is not None else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_latest_version_number(self, obj):
        version = self._latest_version(obj)
        return version.version_number if version is not None else None


class GatewayDatasetStatsSerializer(serializers.Serializer):
    dataset_id = serializers.UUIDField(read_only=True)
    slug = serializers.CharField(read_only=True)
    category = CategorySerializer(read_only=True)
    published_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_changed_at = serializers.DateTimeField(read_only=True)
    metadata_record_count = serializers.IntegerField(read_only=True)
    tag_count = serializers.IntegerField(read_only=True)
    version_count = serializers.IntegerField(read_only=True)
    downloadable_file_count = serializers.IntegerField(read_only=True)
    structured_file_count = serializers.IntegerField(read_only=True)
    file_formats = serializers.ListField(child=serializers.CharField(), read_only=True)
    latest_version_id = serializers.UUIDField(read_only=True, allow_null=True)
    latest_version_number = serializers.CharField(read_only=True, allow_null=True)
    latest_version_created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    latest_file_id = serializers.UUIDField(read_only=True, allow_null=True)
    latest_filename = serializers.CharField(read_only=True, allow_null=True)
    latest_file_format = serializers.CharField(read_only=True, allow_null=True)


class DatasetFileSchemaColumnSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    type = serializers.CharField(read_only=True)
    observed_types = serializers.ListField(child=serializers.CharField(), read_only=True)
    nullable = serializers.BooleanField(read_only=True)


class DatasetFileSchemaResponseSerializer(serializers.Serializer):
    file_id = serializers.UUIDField(read_only=True)
    filename = serializers.CharField(read_only=True)
    file_format = serializers.CharField(read_only=True)
    structure_type = serializers.CharField(read_only=True)
    column_count = serializers.IntegerField(read_only=True, required=False)
    row_count = serializers.IntegerField(read_only=True, required=False)
    page_count = serializers.IntegerField(read_only=True, required=False)
    columns = DatasetFileSchemaColumnSerializer(many=True, read_only=True, required=False)
    sdmx = serializers.JSONField(read_only=True, required=False)
    document = serializers.JSONField(read_only=True, required=False)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True, required=False)


class DatasetFilePreviewQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, min_value=1, max_value=20, default=5)
    offset = serializers.IntegerField(required=False, min_value=0, default=0)


class DatasetFilePreviewResponseSerializer(serializers.Serializer):
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


class APIConsumerSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = APIConsumer
        fields = (
            "id",
            "name",
            "consumer_type",
            "organization_name",
            "email",
            "status",
        )


class APIKeyRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    consumer_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    organization_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_expires_at(self, value):
        if value is None:
            return value

        from django.utils import timezone

        if value <= timezone.now():
            raise serializers.ValidationError("Expiration must be in the future.")
        return value


class APIKeyDetailSerializer(serializers.ModelSerializer):
    consumer = APIConsumerSummarySerializer(read_only=True)
    scopes = serializers.SerializerMethodField()

    class Meta:
        model = APIKey
        fields = (
            "id",
            "consumer",
            "name",
            "prefix",
            "status",
            "expires_at",
            "last_used_at",
            "revoked_at",
            "created_at",
            "updated_at",
            "scopes",
        )

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_scopes(self, obj):
        return list(obj.scopes.values_list("code", flat=True))


class IssuedAPIKeySerializer(APIKeyDetailSerializer):
    api_key = serializers.CharField(read_only=True)

    class Meta(APIKeyDetailSerializer.Meta):
        fields = APIKeyDetailSerializer.Meta.fields + ("api_key",)


class APIKeyActionResponseSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)


class APIUsageLogSerializer(serializers.ModelSerializer):
    api_key_id = serializers.UUIDField(source="api_key.id", read_only=True, allow_null=True)
    api_key_name = serializers.CharField(source="api_key.name", read_only=True, allow_null=True)
    api_key_prefix = serializers.CharField(source="api_key.prefix", read_only=True, allow_null=True)
    consumer_name = serializers.CharField(source="consumer.name", read_only=True, allow_null=True)

    class Meta:
        model = APIUsageLog
        fields = (
            "id",
            "created_at",
            "api_key_id",
            "api_key_name",
            "api_key_prefix",
            "consumer_name",
            "endpoint",
            "method",
            "status_code",
            "ip_address",
            "user_agent",
            "dataset_id",
            "response_time_ms",
            "error_code",
        )
