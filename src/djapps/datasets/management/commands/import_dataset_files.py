import hashlib
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.text import slugify

from djapps.datasets.models import (
    Category,
    Dataset,
    DatasetFile,
    DatasetMetadata,
    DatasetStatus,
    DatasetVersion,
    generate_unique_slug,
)
from djapps.datasets.serializers import DatasetFileSerializer
from djapps.user_management.models import User


DEFAULT_IMPORT_DIR = Path(settings.BASE_DIR) / "media" / "dataset_files"


class Command(BaseCommand):
    help = "Import fixture dataset files from the media dataset_files directory into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-dir",
            default=str(DEFAULT_IMPORT_DIR),
            help="Directory containing the source files to import.",
        )
        parser.add_argument(
            "--user-email",
            default="dataset-importer@smarthub.local",
            help="Email of the user that will own imported datasets.",
        )
        parser.add_argument(
            "--category-name",
            default="Imported Datasets",
            help="Category to assign to imported datasets.",
        )
        parser.add_argument(
            "--publish",
            action="store_true",
            help="Mark imported datasets as published and visible.",
        )

    def _resolve_user(self, email):
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": "Dataset",
                "last_name": "Importer",
                "is_verified": True,
            },
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        return user

    def _resolve_category(self, name):
        category, _ = Category.objects.get_or_create(
            name=name,
            defaults={"slug": slugify(name) or "imported-datasets"},
        )
        if not category.slug:
            category.slug = generate_unique_slug(category, category.name, fallback="category")
            category.save(update_fields=["slug"])
        return category

    def _read_source_bytes(self, source_path):
        with source_path.open("rb") as handle:
            return handle.read()

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"])
        if not source_dir.exists() or not source_dir.is_dir():
            raise CommandError(f"Source directory does not exist: {source_dir}")

        source_files = sorted(
            path for path in source_dir.iterdir() if path.is_file() and not path.name.startswith(".")
        )
        if not source_files:
            self.stdout.write(self.style.WARNING("No files found to import."))
            return

        user = self._resolve_user(options["user_email"])
        category = self._resolve_category(options["category_name"])
        publish = bool(options["publish"])

        imported = 0
        skipped = 0

        for source_path in source_files:
            raw_bytes = self._read_source_bytes(source_path)
            checksum = hashlib.sha256(raw_bytes).hexdigest()
            if DatasetFile.objects.filter(checksum=checksum).exists():
                skipped += 1
                self.stdout.write(self.style.WARNING(f"Skipped existing file: {source_path.name}"))
                continue

            dataset_slug = generate_unique_slug(
                Dataset(slug=""),
                source_path.stem,
                fallback="dataset",
            )
            dataset = Dataset.objects.create(
                publisher_user=user,
                category=category,
                slug=dataset_slug,
                status=DatasetStatus.PUBLISHED if publish else DatasetStatus.DRAFT,
                visibility=publish,
                published_at=timezone.now() if publish else None,
            )

            DatasetMetadata.objects.create(
                dataset=dataset,
                title=source_path.stem.replace("_", " ").replace("-", " ").title(),
                description=f"Imported from {source_path.name}.",
                license="",
                frequency="",
                region="",
                year=None,
            )

            version = DatasetVersion.objects.create(
                dataset=dataset,
                created_by=user,
                version_number="1.0",
                changelog=f"Imported from {source_path.name}.",
            )

            uploaded_file = ContentFile(raw_bytes, name=source_path.name)
            serializer = DatasetFileSerializer(
                data={
                    "dataset_version_id": str(version.id),
                    "file": uploaded_file,
                    "is_primary": True,
                }
            )
            serializer.is_valid(raise_exception=True)
            serializer.save(uploaded_by=user)

            imported += 1
            self.stdout.write(self.style.SUCCESS(f"Imported: {source_path.name}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete. Imported {imported} file(s), skipped {skipped} existing file(s)."
            )
        )
