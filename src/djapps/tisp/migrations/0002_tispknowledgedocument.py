from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("tisp", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="TispKnowledgeDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_url", models.URLField(unique=True)),
                ("source_type", models.CharField(max_length=30)),
                ("title", models.CharField(max_length=500)),
                ("content", models.TextField(blank=True)),
                ("payload", models.JSONField(default=dict)),
                ("fetched_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "tisp_knowledge_documents",
                "indexes": [
                    models.Index(fields=["source_type"], name="tisp_knowle_source__idx"),
                    models.Index(fields=["fetched_at"], name="tisp_knowle_fetched__idx"),
                ],
            },
        ),
    ]
