from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from ...roles import DEFAULT_GROUPS, ensure_group_permissions


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
            _, missing = ensure_group_permissions(name)

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
