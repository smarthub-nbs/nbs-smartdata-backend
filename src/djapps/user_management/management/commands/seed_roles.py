from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand


DEFAULT_GROUPS = ["guest", "user","developer","researcher","admin", "editor", "super_admin"]

GROUP_PERMISSION_MAP = {
    "guest": (),
    "user": (
        "datasets.view_dataset",
    ),
    "developer": (
        "datasets.view_dataset",
    ),
    "researcher": (
        "datasets.view_dataset",
    ),
    "editor": (
        "datasets.view_dataset",
        "datasets.add_dataset",
        "datasets.change_dataset",
        "datasets.delete_dataset",
    ),
    "admin": (
        "datasets.view_dataset",
        "datasets.view_all_dataset",
        "datasets.add_dataset",
        "datasets.change_dataset",
        "datasets.delete_dataset",
        "datasets.review_dataset",
        "datasets.publish_dataset",
        "user_management.view_user",
        "user_management.add_user",
        "user_management.change_user",
        "user_management.delete_user",
    ),
    "super_admin": (
        "datasets.view_dataset",
        "datasets.view_all_dataset",
        "datasets.add_dataset",
        "datasets.change_dataset",
        "datasets.delete_dataset",
        "datasets.review_dataset",
        "datasets.publish_dataset",
        "user_management.view_user",
        "user_management.add_user",
        "user_management.change_user",
        "user_management.delete_user",
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


class Command(BaseCommand):
    help = "Create baseline auth groups for the project."

    def add_arguments(self, parser):
        parser.add_argument(
            "--groups",
            nargs="+",
            metavar="GROUP",
            help="Optional list of group names to create instead of the defaults.",
        )

    def handle(self, *args, **options):
        group_names = options["groups"] or DEFAULT_GROUPS

        created = []
        existing = []

        for name in group_names:
            group, was_created = Group.objects.get_or_create(name=name)
            if was_created:
                created.append(name)
            else:
                existing.append(name)
            permissions, missing = resolve_permissions(
                GROUP_PERMISSION_MAP.get(name, ())
            )
            group.permissions.set(permissions)

            if missing:
                self.stdout.write(
                    self.style.WARNING(
                        f"Missing permissions for {name}: {', '.join(missing)}"
                    )
                )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created groups: {', '.join(created)}")
            )

        if existing:
            self.stdout.write(
                self.style.WARNING(f"Already existed: {', '.join(existing)}")
            )

        if not created and not existing:
            self.stdout.write("No groups were provided.")
