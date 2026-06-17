import django.db.models.deletion
import uuid
from django.db import migrations, models


def backfill_dataset_categories(apps, schema_editor):
    Category = apps.get_model("datasets", "Category")
    Dataset = apps.get_model("datasets", "Dataset")

    category, _ = Category.objects.get_or_create(
        slug="uncategorized",
        defaults={"name": "Uncategorized"},
    )
    Dataset.objects.filter(category_id__isnull=True).update(category_id=category)


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=50)),
                ("slug", models.CharField(max_length=50)),
            ],
            options={
                "db_table": "category",
                "verbose_name": "Category",
                "verbose_name_plural": "Categories",
            },
        ),
        migrations.AlterModelTable(
            name="dataset",
            table="datasets",
        ),
        migrations.AlterModelTable(
            name="datasetfile",
            table="dataset_files",
        ),
        migrations.AlterModelTable(
            name="datasetstatushistory",
            table="dataset_status_history",
        ),
        migrations.AlterModelTable(
            name="datasettag",
            table="dataset_tags",
        ),
        migrations.AlterModelTable(
            name="datasetversion",
            table="dataset_versions",
        ),
        migrations.AlterModelTable(
            name="tag",
            table="tags",
        ),
        migrations.AddField(
            model_name="dataset",
            name="category_id",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="datasets.category",
            ),
        ),
        migrations.RunPython(backfill_dataset_categories, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="dataset",
            name="category_id",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="datasets.category",
            ),
        ),
        migrations.CreateModel(
            name="DatasetMetadata",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("title", models.CharField(max_length=100)),
                ("description", models.TextField()),
                ("license", models.CharField(max_length=100)),
                (
                    "dataset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metadata",
                        to="datasets.dataset",
                    ),
                ),
            ],
            options={
                "verbose_name": "Dataset Metadata",
                "verbose_name_plural": "Dataset Metadata",
                "db_table": "dataset_metadata",
            },
        ),
        migrations.CreateModel(
            name="IndexingStatus",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("indexed_at", models.DateTimeField(auto_now_add=True)),
                ("status", models.CharField(max_length=20)),
                ("details", models.TextField(blank=True)),
                (
                    "dataset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="indexing_status",
                        to="datasets.dataset",
                    ),
                ),
            ],
            options={
                "verbose_name": "Indexing Status",
                "verbose_name_plural": "Indexing Statuses",
                "db_table": "indexing_status",
            },
        ),
    ]
