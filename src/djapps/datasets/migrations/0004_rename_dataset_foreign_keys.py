from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0003_alter_dataset_options"),
    ]

    operations = [
        migrations.RenameField(
            model_name="dataset",
            old_name="publisher_user_id",
            new_name="publisher_user",
        ),
        migrations.RenameField(
            model_name="dataset",
            old_name="category_id",
            new_name="category",
        ),
    ]
