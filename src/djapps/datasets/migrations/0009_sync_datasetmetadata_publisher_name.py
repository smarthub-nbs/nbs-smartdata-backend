from django.db import migrations


def _build_publisher_name(publisher_user):
    full_name = " ".join(
        part for part in [publisher_user.first_name, publisher_user.last_name] if part
    ).strip()
    return full_name or publisher_user.email


def sync_datasetmetadata_publisher_name(apps, schema_editor):
    DatasetMetadata = apps.get_model("datasets", "DatasetMetadata")

    queryset = DatasetMetadata.objects.select_related("dataset__publisher_user")
    for metadata in queryset.iterator():
        publisher_name = _build_publisher_name(metadata.dataset.publisher_user)
        if metadata.publisher_name != publisher_name:
            metadata.publisher_name = publisher_name
            metadata.save(update_fields=["publisher_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0008_alter_dataset_options_alter_dataset_managers"),
    ]

    operations = [
        migrations.RunPython(
            sync_datasetmetadata_publisher_name,
            migrations.RunPython.noop,
        ),
    ]
