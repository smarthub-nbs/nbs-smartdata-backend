from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import FieldTextFilter, RangeDateTimeFilter, RangeNumericFilter
from unfold.paginator import InfinitePaginator

from .models import (
    CensusDataRecord,
    TispApiResponseCache,
    TispDataValue,
    TispKnowledgeDocument,
)


class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)


class LargeTableAdminMixin:
    paginator = InfinitePaginator
    show_full_result_count = False
    list_per_page = 50


@admin.register(TispKnowledgeDocument)
class TispKnowledgeDocumentAdmin(ReadOnlyAdminMixin, ModelAdmin):
    list_display = ("title", "source_type", "source_url", "fetched_at")
    list_filter = (
        ("source_type", FieldTextFilter),
        ("fetched_at", RangeDateTimeFilter),
    )
    search_fields = ("title", "source_url", "content")
    date_hierarchy = "fetched_at"
    ordering = ("-fetched_at",)


@admin.register(CensusDataRecord)
class CensusDataRecordAdmin(ReadOnlyAdminMixin, LargeTableAdminMixin, ModelAdmin):
    list_display = (
        "area_name",
        "area_level",
        "indicator_name",
        "time_name",
        "data_value",
        "tag",
        "fetched_at",
    )
    list_filter = (
        ("area_level", FieldTextFilter),
        ("time_name", FieldTextFilter),
        ("tag", RangeNumericFilter),
        ("data_value", RangeNumericFilter),
        ("fetched_at", RangeDateTimeFilter),
    )
    search_fields = ("record_key", "area_name", "area_code", "indicator_name", "time_name")
    date_hierarchy = "fetched_at"
    ordering = ("area_name", "indicator_name", "time_name")


@admin.register(TispApiResponseCache)
class TispApiResponseCacheAdmin(ReadOnlyAdminMixin, ModelAdmin):
    list_display = ("endpoint", "params_hash", "fetched_at")
    list_filter = (
        ("endpoint", FieldTextFilter),
        ("fetched_at", RangeDateTimeFilter),
    )
    search_fields = ("endpoint", "params_hash")
    date_hierarchy = "fetched_at"
    ordering = ("-fetched_at",)


@admin.register(TispDataValue)
class TispDataValueAdmin(ReadOnlyAdminMixin, LargeTableAdminMixin, ModelAdmin):
    list_display = (
        "indicator_name",
        "area_name",
        "area_level",
        "time_name",
        "datavalue",
        "source_name",
        "fetched_at",
    )
    list_filter = (
        ("area_level", FieldTextFilter),
        ("time_name", FieldTextFilter),
        ("source_name", FieldTextFilter),
        ("tag", RangeNumericFilter),
        ("datavalue", RangeNumericFilter),
        ("fetched_at", RangeDateTimeFilter),
    )
    search_fields = (
        "indicator_name",
        "area_name",
        "area_code",
        "source_name",
        "source_mda",
        "time_name",
    )
    date_hierarchy = "fetched_at"
    ordering = ("indicator_name", "area_name", "time_name")
