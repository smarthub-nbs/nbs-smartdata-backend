from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("tisp", "0002_tispknowledgedocument")]
    operations = [
        migrations.CreateModel(
            name="CensusDataRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("record_key", models.CharField(max_length=160, unique=True)),
                ("area_name", models.CharField(max_length=255)),
                ("area_code", models.CharField(blank=True, max_length=50)),
                ("area_level", models.CharField(blank=True, max_length=20)),
                ("parent_code", models.CharField(blank=True, max_length=50)),
                ("indicator_name", models.CharField(max_length=500)),
                ("time_name", models.CharField(blank=True, max_length=100)),
                ("data_value", models.FloatField(blank=True, null=True)),
                ("tag", models.IntegerField(default=0)),
                ("raw", models.JSONField(default=dict)),
                ("fetched_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "tisp_census_data_records",
                "indexes": [
                    models.Index(fields=["indicator_name"], name="tisp_census_indica_idx"),
                    models.Index(fields=["area_name"], name="tisp_census_area_nam_idx"),
                    models.Index(fields=["time_name"], name="tisp_census_time_na_idx"),
                ],
            },
        )
    ]
