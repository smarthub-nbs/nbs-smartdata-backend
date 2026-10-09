from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    ChoicesDropdownFilter,
    FieldTextFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
)
from unfold.decorators import display
from unfold.paginator import InfinitePaginator

from .models import APIConsumer, APIKey, APIKeyScope, APIScope, APIUsageLog


class TimestampedAdminMixin:
    readonly_fields = ("created_at", "updated_at", "deleted_at")


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


CONSUMER_STATUS_LABELS = {
    "active": "success",
    "suspended": "danger",
}

API_KEY_STATUS_LABELS = {
    "active": "success",
    "revoked": "danger",
    "expired": "warning",
}

HTTP_STATUS_LABELS = {
    "success": "success",
    "redirect": "info",
    "client_error": "warning",
    "server_error": "danger",
}


class APIKeyInline(TabularInline):
    model = APIKey
    extra = 0
    per_page = 10
    fields = ("name", "prefix", "status", "expires_at", "last_used_at", "created_at")
    readonly_fields = ("prefix", "hashed_key", "last_used_at", "created_at", "updated_at", "deleted_at")
    show_change_link = True


@admin.register(APIConsumer)
class APIConsumerAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = (
        "name",
        "user",
        "consumer_type",
        "organization_name",
        "email",
        "status_badge",
        "created_at",
    )
    list_filter = (
        ("consumer_type", ChoicesDropdownFilter),
        ("status", ChoicesDropdownFilter),
        ("user", AutocompleteSelectFilter),
        ("created_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    search_fields = ("name", "organization_name", "email", "user__email")
    autocomplete_fields = ("user",)
    ordering = ("name",)
    inlines = (APIKeyInline,)

    def get_queryset(self, request):
        return APIConsumer.objects.select_related("user")

    @display(description="Status", ordering="status", label=CONSUMER_STATUS_LABELS)
    def status_badge(self, obj):
        return (obj.status, obj.get_status_display())


@admin.register(APIScope)
class APIScopeAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = ("code", "name", "is_active", "created_at")
    list_filter = ("is_active", "created_at", "deleted_at")
    search_fields = ("code", "name", "description")
    ordering = ("code",)


class APIKeyScopeInline(TabularInline):
    model = APIKeyScope
    extra = 0
    per_page = 10
    autocomplete_fields = ("scope",)


@admin.register(APIKey)
class APIKeyAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = (
        "name",
        "consumer",
        "prefix",
        "status_badge",
        "expires_at",
        "last_used_at",
        "created_at",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("consumer", AutocompleteSelectFilter),
        ("expires_at", RangeDateTimeFilter),
        ("last_used_at", RangeDateTimeFilter),
        ("created_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    search_fields = ("name", "prefix", "consumer__name", "consumer__email", "consumer__user__email")
    autocomplete_fields = ("consumer",)
    readonly_fields = (
        "prefix",
        "hashed_key",
        "last_used_at",
        "revoked_at",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    ordering = ("-created_at",)
    inlines = (APIKeyScopeInline,)

    def get_queryset(self, request):
        return APIKey.objects.select_related("consumer", "consumer__user")

    @display(description="Status", ordering="status", label=API_KEY_STATUS_LABELS)
    def status_badge(self, obj):
        return (obj.status, obj.get_status_display())


@admin.register(APIKeyScope)
class APIKeyScopeAdmin(TimestampedAdminMixin, ModelAdmin):
    list_display = ("api_key", "scope", "created_at")
    list_filter = (
        ("api_key", AutocompleteSelectFilter),
        ("scope", AutocompleteSelectFilter),
        ("created_at", RangeDateTimeFilter),
        ("deleted_at", RangeDateTimeFilter),
    )
    search_fields = ("api_key__name", "api_key__prefix", "scope__code", "scope__name")
    autocomplete_fields = ("api_key", "scope")

    def get_queryset(self, request):
        return APIKeyScope.objects.select_related("api_key", "scope")


@admin.register(APIUsageLog)
class APIUsageLogAdmin(ReadOnlyAdminMixin, LargeTableAdminMixin, ModelAdmin):
    list_display = (
        "created_at",
        "method",
        "endpoint",
        "status_code_badge",
        "consumer",
        "api_key",
        "response_time_ms",
        "ip_address",
    )
    list_filter = (
        ("method", FieldTextFilter),
        ("status_code", RangeNumericFilter),
        ("consumer", AutocompleteSelectFilter),
        ("api_key", AutocompleteSelectFilter),
        ("created_at", RangeDateTimeFilter),
    )
    search_fields = (
        "endpoint",
        "method",
        "error_code",
        "consumer__name",
        "consumer__email",
        "api_key__name",
        "api_key__prefix",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return APIUsageLog.objects.select_related("consumer", "api_key")

    @display(description="Status", ordering="status_code", label=HTTP_STATUS_LABELS)
    def status_code_badge(self, obj):
        if obj.status_code >= 500:
            status_group = "server_error"
        elif obj.status_code >= 400:
            status_group = "client_error"
        elif obj.status_code >= 300:
            status_group = "redirect"
        else:
            status_group = "success"

        return (status_group, obj.status_code)
