from django.contrib.auth.models import Group, Permission

ROLE_GUEST = "guest"
ROLE_USER = "user"
ROLE_DEVELOPER = "developer"
ROLE_RESEARCHER = "researcher"
ROLE_EDITOR = "editor"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"

ADMIN_GROUPS = (ROLE_ADMIN, ROLE_SUPER_ADMIN)
DEFAULT_GROUPS = [
    ROLE_GUEST,
    ROLE_USER,
    ROLE_DEVELOPER,
    ROLE_RESEARCHER,
    ROLE_EDITOR,
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
]

DATASET_READ_PERMISSIONS = (
    "datasets.view_dataset",
)

DATASET_EDITOR_PERMISSIONS = (
    "datasets.view_dataset",
    "datasets.add_dataset",
    "datasets.change_dataset",
    "datasets.delete_dataset",
)

DATASET_ADMIN_PERMISSIONS = (
    "datasets.view_dataset",
    "datasets.view_all_dataset",
    "datasets.add_dataset",
    "datasets.change_dataset",
    "datasets.delete_dataset",
    "datasets.review_dataset",
    "datasets.publish_dataset",
)

DATASET_TAXONOMY_ADMIN_PERMISSIONS = (
    "datasets.add_category",
    "datasets.change_category",
    "datasets.delete_category",
    "datasets.add_tag",
    "datasets.change_tag",
    "datasets.delete_tag",
)

USER_ADMIN_PERMISSIONS = (
    "user_management.view_user",
    "user_management.add_user",
    "user_management.change_user",
)

SUPER_ADMIN_EXTRA_PERMISSIONS = (
    "user_management.delete_user",
)

DEVELOPER_API_PERMISSIONS = (
    "gateway.add_apiconsumer",
    "gateway.view_apiconsumer",
    "gateway.change_apiconsumer",
    "gateway.add_apikey",
    "gateway.view_apikey",
    "gateway.change_apikey",
    "gateway.view_apiusagelog",
)

GROUP_PERMISSION_MAP = {
    ROLE_GUEST: (),
    ROLE_USER: DATASET_READ_PERMISSIONS,
    ROLE_DEVELOPER: DATASET_READ_PERMISSIONS + DEVELOPER_API_PERMISSIONS,
    ROLE_RESEARCHER: DATASET_READ_PERMISSIONS,
    ROLE_EDITOR: DATASET_EDITOR_PERMISSIONS,
    ROLE_ADMIN: (
        DATASET_ADMIN_PERMISSIONS
        + DATASET_TAXONOMY_ADMIN_PERMISSIONS
        + USER_ADMIN_PERMISSIONS
        + DEVELOPER_API_PERMISSIONS
    ),
    ROLE_SUPER_ADMIN: (
        DATASET_ADMIN_PERMISSIONS
        + DATASET_TAXONOMY_ADMIN_PERMISSIONS
        + USER_ADMIN_PERMISSIONS
        + SUPER_ADMIN_EXTRA_PERMISSIONS
        + DEVELOPER_API_PERMISSIONS
    ),
}


def resolve_permissions(permission_labels):
    permissions = []
    missing = []

    for label in permission_labels:
        app_label, codename = label.split(".", 1)
        permission = Permission.objects.filter(
            content_type__app_label=app_label,
            codename=codename,
        ).first()
        if permission is None:
            missing.append(label)
            continue
        permissions.append(permission)

    return permissions, missing


def ensure_group_permissions(group_name):
    group, _ = Group.objects.get_or_create(name=group_name)
    permissions, missing = resolve_permissions(GROUP_PERMISSION_MAP.get(group_name, ()))
    group.permissions.set(permissions)
    return group, missing


def ensure_default_user_group(user):
    if getattr(user, "is_superuser", False):
        return None

    group, _ = ensure_group_permissions(ROLE_USER)
    user.groups.add(group)
    return group


def sync_user_groups(user, groups):
    desired_names = {group.name for group in groups}
    if not getattr(user, "is_superuser", False):
        desired_names.add(ROLE_USER)

    resolved_groups = [ensure_group_permissions(name)[0] for name in sorted(desired_names)]
    user.groups.set(resolved_groups)
    return resolved_groups
