from django.contrib import admin

from .models import (
    Category,
    Dataset,
    DatasetAuditLog,
    DatasetFile,
    DatasetMetadata,
    DatasetStatusHistory,
    DatasetTag,
    DatasetVersion,
    IndexingStatus,
    Tag,
)


class TimestampedAdminMixin:
    readonly_fields = ("created_at", "updated_at", "deleted_at")


class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DatasetMetadataInline(admin.StackedInline):
    model = DatasetMetadata
    extra = 0
    max_num = 1
    readonly_fields = ("publisher_name", "created_at", "updated_at", "deleted_at")


class DatasetTagInline(admin.TabularInline):
    model = DatasetTag
    extra = 0
    autocomplete_fields = ("tag",)


class DatasetVersionInline(admin.TabularInline):
    model = DatasetVersion
    extra = 0
    fields = ("version_number", "created_by", "created_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("created_by",)
    show_change_link = True


class DatasetStatusHistoryInline(admin.TabularInline):
    model = DatasetStatusHistory
    extra = 0
    fields = ("old_status", "new_status", "changed_by", "changed_at")
    readonly_fields = ("old_status", "new_status", "reason", "changed_by", "changed_at")
    can_delete = False
    show_change_link = True


class DatasetAuditLogInline(admin.TabularInline):
    model = DatasetAuditLog
    extra = 0
    fields = ("action", "actor", "target_model", "created_at")
    readonly_fields = ("action", "actor", "target_model", "target_id", "details", "created_at")
    can_delete = False
    show_change_link = True


@admin.register(Category)
class CategoryAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "created_at", "updated_at")
    search_fields = ("name", "slug")
    ordering = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "created_at", "updated_at")
    search_fields = ("name", "slug")
    ordering = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Dataset)
class DatasetAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "slug",
        "publisher_user",
        "category",
        "status",
        "visibility",
        "published_at",
        "deleted_at",
        "created_at",
    )
    list_filter = ("status", "visibility", "category", "published_at", "deleted_at")
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

    @admin.action(description="Restore selected datasets")
    def restore_selected_datasets(self, request, queryset):
        queryset.restore()


class DatasetFileInline(admin.TabularInline):
    model = DatasetFile
    extra = 0
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


@admin.register(DatasetVersion)
class DatasetVersionAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ("dataset", "version_number", "created_by", "created_at", "updated_at")
    list_filter = ("created_at", "deleted_at")
    search_fields = ("dataset__slug", "version_number", "created_by__email")
    autocomplete_fields = ("dataset", "created_by")
    ordering = ("-created_at",)
    inlines = (DatasetFileInline,)

    def get_queryset(self, request):
        return DatasetVersion.objects.select_related("dataset", "created_by")


@admin.register(DatasetFile)
class DatasetFileAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "filename",
        "dataset_version",
        "uploaded_by",
        "file_format",
        "file_size",
        "validation_status",
        "is_safe",
        "is_primary",
        "created_at",
    )
    list_filter = (
        "file_format",
        "validation_status",
        "is_safe",
        "is_primary",
        "created_at",
        "deleted_at",
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


@admin.register(DatasetTag)
class DatasetTagAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ("dataset", "tag", "created_at")
    search_fields = ("dataset__slug", "tag__name", "tag__slug")
    list_filter = ("tag", "created_at", "deleted_at")
    autocomplete_fields = ("dataset", "tag")

    def get_queryset(self, request):
        return DatasetTag.objects.select_related("dataset", "tag")


@admin.register(DatasetMetadata)
class DatasetMetadataAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "dataset",
        "title",
        "publisher_name",
        "frequency",
        "region",
        "year",
        "created_at",
    )
    list_filter = ("frequency", "region", "year", "deleted_at")
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
class DatasetStatusHistoryAdmin(ReadOnlyAdminMixin, TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ("dataset", "old_status", "new_status", "changed_by", "changed_at")
    list_filter = ("old_status", "new_status", "changed_at")
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
class IndexingStatusAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ("dataset", "status", "indexed_at", "created_at")
    list_filter = ("status", "indexed_at", "deleted_at")
    search_fields = ("dataset__slug", "status", "details")
    autocomplete_fields = ("dataset",)
    readonly_fields = ("indexed_at", "created_at", "updated_at", "deleted_at")
    ordering = ("-indexed_at",)

    def get_queryset(self, request):
        return IndexingStatus.objects.select_related("dataset")


@admin.register(DatasetAuditLog)
class DatasetAuditLogAdmin(ReadOnlyAdminMixin, TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ("dataset", "action", "actor", "target_model", "created_at")
    list_filter = ("action", "target_model", "created_at")
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
