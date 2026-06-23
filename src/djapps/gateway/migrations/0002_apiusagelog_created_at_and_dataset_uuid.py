from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ("gateway", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="apiusagelog",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=timezone.now),
            preserve_default=False,
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE api_usage_log "
                        "ALTER COLUMN dataset_id TYPE uuid USING NULL"
                    ),
                    reverse_sql=(
                        "ALTER TABLE api_usage_log "
                        "ALTER COLUMN dataset_id TYPE integer USING NULL"
                    ),
                ),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="apiusagelog",
                    name="dataset_id",
                    field=models.UUIDField(blank=True, null=True),
                ),
            ],
        ),
    ]
