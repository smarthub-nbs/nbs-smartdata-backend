from django import forms
from django.contrib import admin
from django.utils import timezone
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    BooleanRadioFilter,
    ChoicesDropdownFilter,
    FieldTextFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
)
from unfold.decorators import display
from unfold.paginator import InfinitePaginator

from .models import (
    Category,
    Dataset,
    DatasetAuditLog,
    DatasetBookmark,
    DatasetBulkActionJobStatus,
    DatasetBulkActionJob,
    DatasetBulkUploadJob,
    DatasetBulkUploadJobItem,
    DatasetFile,
    DatasetStatus,
    DatasetMetadata,
    DatasetStatusHistory,
    DatasetTag,
    DatasetVersion,
    FileValidationStatus,
    IndexingStatus,
    Region,
    Tag,
)
from .serializers import inspect_dataset_file


class TimestampedAdminMixin:
    readonly_fields = ("created_at", "updated_at", "deleted_at")


class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class LargeTableAdminMixin:
    paginator = InfinitePaginator
    show_full_result_count = False
    list_per_page = 50


DATASET_STATUS_LABELS = {
    DatasetStatus.DRAFT: "info",
    DatasetStatus.IN_REVIEW: "warning",
    DatasetStatus.APPROVED: "success",
    DatasetStatus.REJECTED: "danger",
    DatasetStatus.PUBLISHED: "primary",
}

FILE_VALIDATION_STATUS_LABELS = {
    FileValidationStatus.VALIDATED: "success",
    FileValidationStatus.REJECTED: "danger",
}

JOB_STATUS_LABELS = {
    DatasetBulkActionJobStatus.QUEUED: "info",
    DatasetBulkActionJobStatus.RUNNING: "warning",
    DatasetBulkActionJobStatus.COMPLETED: "success",
    DatasetBulkActionJobStatus.FAILED: "danger",
}


class DatasetMetadataInline(StackedInline):
    model = DatasetMetadata
    extra = 0
    max_num = 1
    readonly_fields = ("publisher_name", "created_at", "updated_at", "deleted_at")


class DatasetTagInline(TabularInline):
    model = DatasetTag
    extra = 0
    autocomplete_fields = ("tag",)


class DatasetVersionInline(TabularInline):
    model = DatasetVersion
    extra = 0
    per_page = 10
    fields = ("version_number", "created_by", "created_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("created_by",)
    show_change_link = True


class DatasetStatusHistoryInline(TabularInline):
    model = DatasetStatusHistory
    extra = 0
    per_page = 10
    fields = ("old_status", "new_status", "changed_by", "changed_at")
    readonly_fields = ("old_status", "new_status", "reason", "changed_by", "changed_at")
    can_delete = False
    show_change_link = True


class DatasetAuditLogInline(TabularInline):
    model = DatasetAuditLog
    extra = 0
    per_page = 10
    fields = ("action", "actor", "target_model", "created_at")
    readonly_fields = ("action", "actor", "target_model", "target_id", "details", "created_at")
    can_delete = False
    show_change_link = True


@admin.register(Category)
class CategoryAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = ("name", "slug", "created_at", "updated_at")
    search_fields = ("name", "slug")
    ordering = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = ("name", "slug", "created_at", "updated_at")
    search_fields = ("name", "slug")
    ordering = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Region)
class RegionAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = ("name", "created_at", "updated_at")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Dataset)
class DatasetAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = (
        "slug",
        "publisher_user",
        "category",
        "status_badge",
        "visibility",
        "published_at",
        "deleted_at",
        "created_at",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("visibility", BooleanRadioFilter),
        ("publisher_user", AutocompleteSelectFilter),
        ("category", AutocompleteSelectFilter),
        ("published_at", RangeDateTimeFilter),
        ("created_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    search_fields = (
        "slug",
        "publisher_user__email",
        "publisher_user__first_name",
        "publisher_user__last_name",
        "category__name",
        "metadata__title",
        "metadata__publisher_name",
    )
    autocomplete_fields = ("publisher_user", "category")
    readonly_fields = ("created_at", "updated_at", "deleted_at", "published_at")
    ordering = ("-created_at",)
    inlines = (
        DatasetMetadataInline,
        DatasetTagInline,
        DatasetVersionInline,
        DatasetStatusHistoryInline,
        DatasetAuditLogInline,
    )
    actions = ("restore_selected_datasets",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "slug",
                    "publisher_user",
                    "category",
                    "status",
                    "visibility",
                    "published_at",
                )
            },
        ),
        (
            "Lifecycle",
            {"fields": ("created_at", "updated_at", "deleted_at")},
        ),
    )

    def get_queryset(self, request):
        return (
            Dataset.all_objects.select_related("publisher_user", "category")
            .prefetch_related("metadata")
        )

    @display(description="Status", ordering="status", label=DATASET_STATUS_LABELS)
    def status_badge(self, obj):
        return (obj.status, obj.get_status_display())

    @admin.action(description="Restore selected datasets")
    def restore_selected_datasets(self, request, queryset):
        queryset.restore()


class DatasetFileInline(TabularInline):
    model = DatasetFile
    extra = 0
    per_page = 10
    fields = (
        "filename",
        "uploaded_by",
        "file_format",
        "file_size",
        "validation_status",
        "is_safe",
        "is_primary",
    )
    readonly_fields = (
        "filename",
        "file_size",
        "file_format",
        "checksum",
        "validation_status",
        "validated_at",
        "validation_notes",
        "is_safe",
        "uploaded_by",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    can_delete = False
    show_change_link = True


class DatasetFileAdminForm(forms.ModelForm):
    class Meta:
        model = DatasetFile
        fields = "__all__"

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        if uploaded_file is None:
            return uploaded_file

        inspection = inspect_dataset_file(uploaded_file)
        if inspection["errors"]:
            raise forms.ValidationError(" ".join(inspection["errors"]))

        self.cleaned_data["_dataset_file_inspection"] = inspection
        return uploaded_file


@admin.register(DatasetVersion)
class DatasetVersionAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = ("dataset", "version_number", "created_by", "created_at", "updated_at")
    list_filter = ("created_at", "deleted_at")
    search_fields = ("dataset__slug", "version_number", "created_by__email")
    autocomplete_fields = ("dataset", "created_by")
    ordering = ("-created_at",)
    inlines = (DatasetFileInline,)

    def get_queryset(self, request):
        return DatasetVersion.objects.select_related("dataset", "created_by")


@admin.register(DatasetFile)
class DatasetFileAdmin(TimestampedAdminMixin, ModelAdmin):
    form = DatasetFileAdminForm
    list_display = (
        "filename",
        "dataset_version",
        "uploaded_by",
        "file_format",
        "file_size",
        "validation_status_badge",
        "is_safe",
        "is_primary",
        "created_at",
    )
    list_filter = (
        ("file_format", FieldTextFilter),
        ("validation_status", ChoicesDropdownFilter),
        ("is_safe", BooleanRadioFilter),
        ("is_primary", BooleanRadioFilter),
        ("uploaded_by", AutocompleteSelectFilter),
        ("created_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    search_fields = (
        "filename",
        "checksum",
        "dataset_version__dataset__slug",
        "uploaded_by__email",
    )
    autocomplete_fields = ("dataset_version", "uploaded_by")
    readonly_fields = (
        "filename",
        "file_size",
        "file_format",
        "checksum",
        "validated_at",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return DatasetFile.objects.select_related("dataset_version__dataset", "uploaded_by")

    def save_model(self, request, obj, form, change):
        inspection = form.cleaned_data.get("_dataset_file_inspection")
        if inspection is not None:
            obj.filename = inspection["filename"]
            obj.file_size = inspection["file_size"]
            obj.file_format = inspection["file_format"]
            obj.checksum = inspection["checksum"]
            obj.validation_status = FileValidationStatus.VALIDATED
            obj.validated_at = timezone.now()
            obj.validation_notes = "Automatic validation passed."
            obj.is_safe = True

        if obj.uploaded_by_id is None:
            obj.uploaded_by = request.user

        super().save_model(request, obj, form, change)

    @display(
        description="Validation",
        ordering="validation_status",
        label=FILE_VALIDATION_STATUS_LABELS,
    )
    def validation_status_badge(self, obj):
        return (obj.validation_status, obj.get_validation_status_display())


@admin.register(DatasetTag)
class DatasetTagAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = ("dataset", "tag", "created_at")
    search_fields = ("dataset__slug", "tag__name", "tag__slug")
    list_filter = (
        ("tag", AutocompleteSelectFilter),
        ("created_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    autocomplete_fields = ("dataset", "tag")

    def get_queryset(self, request):
        return DatasetTag.objects.select_related("dataset", "tag")


@admin.register(DatasetBookmark)
class DatasetBookmarkAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = ("user", "dataset", "created_at")
    list_filter = (
        ("user", AutocompleteSelectFilter),
        ("dataset", AutocompleteSelectFilter),
        ("created_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    search_fields = ("user__email", "dataset__slug", "dataset__metadata__title")
    autocomplete_fields = ("user", "dataset")
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return DatasetBookmark.objects.select_related("user", "dataset")


@admin.register(DatasetMetadata)
class DatasetMetadataAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = (
        "dataset",
        "title",
        "publisher_name",
        "frequency",
        "region",
        "year",
        "created_at",
    )
    list_filter = (
        ("frequency", ChoicesDropdownFilter),
        ("region", FieldTextFilter),
        ("year", RangeNumericFilter),
        ("created_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    search_fields = (
        "dataset__slug",
        "title",
        "publisher_name",
        "region",
        "license",
    )
    autocomplete_fields = ("dataset",)
    readonly_fields = ("publisher_name", "created_at", "updated_at", "deleted_at")

    def get_queryset(self, request):
        return DatasetMetadata.objects.select_related("dataset")


@admin.register(DatasetStatusHistory)
class DatasetStatusHistoryAdmin(
    ReadOnlyAdminMixin,
    LargeTableAdminMixin,
    TimestampedAdminMixin,
    ModelAdmin,
):
    list_display = ("dataset", "old_status", "new_status", "changed_by", "changed_at")
    list_filter = (
        ("old_status", FieldTextFilter),
        ("new_status", FieldTextFilter),
        ("changed_by", AutocompleteSelectFilter),
        ("changed_at", RangeDateTimeFilter),
    )
    search_fields = ("dataset__slug", "changed_by__email", "reason")
    autocomplete_fields = ("dataset", "changed_by")
    readonly_fields = (
        "dataset",
        "changed_by",
        "old_status",
        "new_status",
        "reason",
        "changed_at",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    ordering = ("-changed_at",)

    def get_queryset(self, request):
        return DatasetStatusHistory.objects.select_related("dataset", "changed_by")


@admin.register(IndexingStatus)
class IndexingStatusAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = ("dataset", "status", "indexed_at", "created_at")
    list_filter = (
        ("status", FieldTextFilter),
        ("dataset", AutocompleteSelectFilter),
        ("indexed_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    search_fields = ("dataset__slug", "status", "details")
    autocomplete_fields = ("dataset",)
    readonly_fields = ("indexed_at", "created_at", "updated_at", "deleted_at")
    ordering = ("-indexed_at",)

    def get_queryset(self, request):
        return IndexingStatus.objects.select_related("dataset")


@admin.register(DatasetAuditLog)
class DatasetAuditLogAdmin(
    ReadOnlyAdminMixin,
    LargeTableAdminMixin,
    TimestampedAdminMixin,
    ModelAdmin,
):
    list_display = ("dataset", "action", "actor", "target_model", "created_at")
    list_filter = (
        ("action", FieldTextFilter),
        ("target_model", FieldTextFilter),
        ("actor", AutocompleteSelectFilter),
        ("created_at", RangeDateTimeFilter),
    )
    search_fields = (
        "dataset__slug",
        "actor__email",
        "target_model",
        "details",
    )
    autocomplete_fields = ("dataset", "actor")
    readonly_fields = (
        "dataset",
        "actor",
        "action",
        "target_model",
        "target_id",
        "details",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return DatasetAuditLog.objects.select_related("dataset", "actor")


@admin.register(DatasetBulkActionJob)
class DatasetBulkActionJobAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = (
        "action",
        "status_badge",
        "requested_by",
        "requested_count",
        "processed_count",
        "failed_count",
        "started_at",
        "completed_at",
        "created_at",
    )
    list_filter = (
        ("action", FieldTextFilter),
        ("status", ChoicesDropdownFilter),
        ("requested_by", AutocompleteSelectFilter),
        ("created_at", RangeDateTimeFilter),
        ("started_at", RangeDateTimeFilter),
        ("completed_at", RangeDateTimeFilter),
    )
    search_fields = ("requested_by__email", "request_signature", "task_id", "reason", "error")
    autocomplete_fields = ("requested_by",)
    readonly_fields = (
        "task_id",
        "requested_count",
        "processed_count",
        "failed_count",
        "processed",
        "failed",
        "error",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return DatasetBulkActionJob.objects.select_related("requested_by")

    @display(description="Status", ordering="status", label=JOB_STATUS_LABELS)
    def status_badge(self, obj):
        return (obj.status, obj.get_status_display())


class DatasetBulkUploadJobItemInline(TabularInline):
    model = DatasetBulkUploadJobItem
    extra = 0
    per_page = 10
    fields = (
        "filename",
        "dataset",
        "dataset_version",
        "status",
        "is_primary",
        "dataset_file",
        "processed_at",
        "created_at",
    )
    readonly_fields = (
        "filename",
        "dataset",
        "dataset_version",
        "status",
        "result",
        "error",
        "dataset_file",
        "processed_at",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    can_delete = False
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "dataset",
            "dataset_version",
            "dataset_file",
        )


@admin.register(DatasetBulkUploadJob)
class DatasetBulkUploadJobAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = (
        "status_badge",
        "requested_by",
        "total_count",
        "processed_count",
        "failed_count",
        "publish_after_upload",
        "started_at",
        "completed_at",
        "created_at",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("publish_after_upload", BooleanRadioFilter),
        ("requested_by", AutocompleteSelectFilter),
        ("created_at", RangeDateTimeFilter),
        ("started_at", RangeDateTimeFilter),
        ("completed_at", RangeDateTimeFilter),
    )
    search_fields = ("requested_by__email", "request_signature", "task_id", "reason", "error")
    autocomplete_fields = ("requested_by",)
    readonly_fields = (
        "task_id",
        "total_count",
        "processed_count",
        "failed_count",
        "error",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    ordering = ("-created_at",)
    inlines = (DatasetBulkUploadJobItemInline,)

    def get_queryset(self, request):
        return DatasetBulkUploadJob.objects.select_related("requested_by")

    @display(description="Status", ordering="status", label=JOB_STATUS_LABELS)
    def status_badge(self, obj):
        return (obj.status, obj.get_status_display())


@admin.register(DatasetBulkUploadJobItem)
class DatasetBulkUploadJobItemAdmin(
    LargeTableAdminMixin,
    TimestampedAdminMixin,
    ModelAdmin,
):
    list_display = (
        "filename",
        "job",
        "dataset",
        "status_badge",
        "is_primary",
        "dataset_file",
        "processed_at",
        "created_at",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("is_primary", BooleanRadioFilter),
        ("job", AutocompleteSelectFilter),
        ("dataset", AutocompleteSelectFilter),
        ("processed_at", RangeDateTimeFilter),
        ("created_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    search_fields = (
        "filename",
        "job__request_signature",
        "job__task_id",
        "dataset__slug",
        "dataset_file__filename",
        "error",
    )
    autocomplete_fields = ("job", "dataset", "dataset_version", "dataset_file")
    readonly_fields = (
        "result",
        "error",
        "processed_at",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return DatasetBulkUploadJobItem.objects.select_related(
            "job",
            "dataset",
            "dataset_version",
            "dataset_file",
        )

    @display(description="Status", ordering="status", label=JOB_STATUS_LABELS)
    def status_badge(self, obj):
        return (obj.status, obj.get_status_display())
