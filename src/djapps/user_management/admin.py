from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_verified", "is_staff", "is_superuser")
    search_fields = ("email", "first_name", "last_name")
    list_filter = ("is_verified", "is_staff", "is_superuser", "is_active", "groups")
    readonly_fields = ("created_at", "updated_at", "last_login", "last_login_at")
    filter_horizontal = ("groups", "user_permissions")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Access", {"fields": ("groups", "is_verified")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "last_login_at", "created_at", "updated_at")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                    "groups",
                    "is_verified",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )
