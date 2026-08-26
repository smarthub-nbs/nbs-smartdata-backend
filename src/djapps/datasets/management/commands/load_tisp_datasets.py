import json
import re
from collections import defaultdict

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from djapps.datasets.models import (
    Category,
    Dataset,
    DatasetFile,
    DatasetFrequency,
    DatasetMetadata,
    DatasetStatus,
    DatasetTag,
    DatasetVersion,
    Tag,
    generate_unique_slug,
)
from djapps.datasets.serializers import DatasetFileSerializer
from djapps.datasets.geo_tree import canonical_geo_parent
from djapps.user_management.models import User


class Command(BaseCommand):
    help = (
        "Replace catalog datasets with published datasets built from ingested "
        "TISP census and datavalue cache."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Hard-delete all existing catalog datasets before loading.",
        )
        parser.add_argument(
            "--user-email",
            default="nbs-tisp@smarthub.local",
            help="Publisher user for loaded datasets.",
        )

    def handle(self, *args, **options):
        user = self._resolve_user(options["user_email"])
        if options["clean"]:
            removed = self._clean_datasets()
            self.stdout.write(self.style.WARNING(f"Removed {removed} catalog dataset(s)."))

        created = 0
        with transaction.atomic():
            created += self._load_census_datasets(user)
            created += self._load_datavalue_datasets(user)

        self.stdout.write(self.style.SUCCESS(f"Loaded {created} published dataset(s) from TISP cache."))

    def _resolve_user(self, email):
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": "NBS",
                "last_name": "TISP",
                "is_verified": True,
            },
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        return user

    def _clean_datasets(self):
        for dataset_file in DatasetFile.objects.iterator():
            if dataset_file.file:
                dataset_file.file.delete(save=False)
        count = Dataset.all_objects.count()
        Dataset.all_objects.all().hard_delete()
        return count

    def _load_census_datasets(self, user):
        grouped = defaultdict(list)
        for row in CensusDataRecord.objects.order_by("area_level", "area_name").iterator():
            grouped[(row.indicator_name, row.time_name)].append(row)

        created = 0
        for (indicator, time_name), rows in grouped.items():
            payload = [
                {
                    "indicator_name": row.indicator_name,
                    "area_name": row.area_name,
                    "area_code": row.area_code,
                    "area_level": row.area_level,
                    "parent_code": row.parent_code,
                    "geo_parent_code": canonical_geo_parent(
                        row.area_level, row.area_code, row.parent_code
                    ),
                    "time_name": row.time_name,
                    "data_value": row.data_value,
                }
                for row in rows
            ]
            year = self._parse_year(time_name)
            title = f"{indicator} ({time_name})"[:100]
            description = self._census_description(indicator, time_name, rows)
            self._create_dataset(
                user=user,
                title=title,
                description=description,
                category_name=self._category_name(indicator),
                region="National",
                year=year,
                filename=f"{slugify(indicator) or 'census'}-{time_name or 'latest'}.json",
                payload=payload,
                tags=("NBS", "TISP", "Census"),
            )
            created += 1
        return created

    def _load_datavalue_datasets(self, user):
        grouped = defaultdict(list)
        for row in TispDataValue.objects.order_by("area_level", "area_name").iterator():
            key = (row.indicator_name, row.source_name, row.subgroup_name)
            grouped[key].append(row)

        created = 0
        for (indicator, source_name, subgroup), rows in grouped.items():
            if len(rows) < 2:
                continue
            year = self._parse_year(rows[0].time_name) or self._parse_year(source_name)
            title = self._datavalue_title(indicator, subgroup, year)
            description = self._datavalue_description(indicator, subgroup, source_name, rows)
            payload = [
                {
                    "indicator_name": row.indicator_name,
                    "subgroup_name": row.subgroup_name,
                    "area_name": row.area_name,
                    "area_code": row.area_code,
                    "area_level": row.area_level,
                    "parent_code": row.parent_code,
                    "geo_parent_code": canonical_geo_parent(
                        row.area_level, row.area_code, row.parent_code
                    ),
                    "time_name": row.time_name,
                    "datavalue": row.datavalue,
                    "source_name": row.source_name,
                }
                for row in rows
            ]
            self._create_dataset(
                user=user,
                title=title,
                description=description,
                category_name=self._category_name(indicator),
                region="National",
                year=year,
                filename=f"{slugify(title) or 'tisp-indicator'}.json",
                payload=payload,
                tags=("NBS", "TISP", subgroup or "Census"),
            )
            created += 1
        return created

    def _create_dataset(
        self,
        *,
        user,
        title,
        description,
        category_name,
        region,
        year,
        filename,
        payload,
        tags,
    ):
        category = self._resolve_category(category_name)
        dataset = Dataset.objects.create(
            publisher_user=user,
            category=category,
            slug=generate_unique_slug(Dataset(slug=""), title, fallback="tisp-dataset"),
            status=DatasetStatus.PUBLISHED,
            visibility=True,
            published_at=timezone.now(),
        )
        DatasetMetadata.objects.create(
            dataset=dataset,
            title=title[:100],
            description=description,
            license="Official NBS public data",
            frequency=DatasetFrequency.ANNUAL,
            region=region,
            year=year,
        )
        version = DatasetVersion.objects.create(
            dataset=dataset,
            created_by=user,
            version_number="1.0",
            changelog="Loaded from ingested TISP/census cache.",
        )
        for tag_name in tags:
            if not tag_name:
                continue
            tag, _ = Tag.objects.get_or_create(
                name=tag_name[:50],
                defaults={"slug": slugify(tag_name)[:50] or "tag"},
            )
            DatasetTag.objects.get_or_create(dataset=dataset, tag=tag)

        raw_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        serializer = DatasetFileSerializer(
            data={
                "dataset_version_id": str(version.id),
                "file": ContentFile(raw_bytes, name=filename),
                "is_primary": True,
            }
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(uploaded_by=user)
        return dataset

    def _resolve_category(self, name):
        category, _ = Category.objects.get_or_create(
            name=name,
            defaults={"slug": slugify(name) or "uncategorized"},
        )
        if not category.slug:
            category.slug = generate_unique_slug(category, category.name, fallback="category")
            category.save(update_fields=["slug"])
        return category

    @staticmethod
    def _category_name(indicator):
        lowered = (indicator or "").lower()
        if "population" in lowered:
            return "Population"
        if "literate" in lowered or "education" in lowered:
            return "Education"
        if "agricultur" in lowered:
            return "Agriculture"
        return "Uncategorized"

    @staticmethod
    def _parse_year(value):
        if not value:
            return None
        match = re.search(r"(?:19|20)\d{2}", str(value))
        return int(match.group(0)) if match else None

    @staticmethod
    def _format_value(value):
        if value is None:
            return "n/a"
        number = float(value)
        if number.is_integer():
            return f"{int(number):,}"
        return f"{number:,.2f}"

    def _census_description(self, indicator, time_name, rows):
        national = next(
            (row for row in rows if row.area_code == "TZ" or row.area_name.lower() == "tanzania"),
            rows[0],
        )
        return (
            f"{indicator} from the NBS TISP census map ({time_name}). "
            f"{national.area_name} was {self._format_value(national.data_value)}. "
            f"{len(rows)} area records."
        )

    def _datavalue_title(self, indicator, subgroup, year):
        parts = [indicator]
        if subgroup:
            parts.append(subgroup)
        if year:
            parts.append(str(year))
        return " — ".join(parts)[:100]

    def _datavalue_description(self, indicator, subgroup, source_name, rows):
        national = next(
            (row for row in rows if row.area_code == "TZ" or row.area_name.lower() == "tanzania"),
            rows[0],
        )
        focus = f"{indicator} ({subgroup})" if subgroup else indicator
        source = source_name or "NBS TISP"
        return (
            f"{focus} from {source}. "
            f"{national.area_name} was {self._format_value(national.datavalue)}. "
            f"{len(rows)} area records."
        )
