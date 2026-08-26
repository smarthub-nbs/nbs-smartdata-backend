from django.db import models
from django.utils import timezone


class TispKnowledgeDocument(models.Model):
    """A locally searchable snapshot of an NBS Sensa/TISP source."""

    source_url = models.URLField(unique=True)
    source_type = models.CharField(max_length=30)
    title = models.CharField(max_length=500)
    content = models.TextField(blank=True)
    payload = models.JSONField(default=dict)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tisp_knowledge_documents"
        indexes = (
            models.Index(fields=("source_type",)),
            models.Index(fields=("fetched_at",)),
        )

    def __str__(self):
        return self.title


class CensusDataRecord(models.Model):
    """Normalized records returned by the public census map data endpoint."""

    record_key = models.CharField(max_length=160, unique=True)
    area_name = models.CharField(max_length=255)
    area_code = models.CharField(max_length=50, blank=True)
    area_level = models.CharField(max_length=20, blank=True)
    parent_code = models.CharField(max_length=50, blank=True)
    indicator_name = models.CharField(max_length=500)
    time_name = models.CharField(max_length=100, blank=True)
    data_value = models.FloatField(null=True, blank=True)
    tag = models.IntegerField(default=0)
    raw = models.JSONField(default=dict)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tisp_census_data_records"
        indexes = (
            models.Index(fields=("indicator_name",)),
            models.Index(fields=("area_name",)),
            models.Index(fields=("time_name",)),
        )


class TispApiResponseCache(models.Model):
    endpoint = models.CharField(max_length=120)
    params_hash = models.CharField(max_length=64)
    params = models.JSONField(default=dict)
    response = models.JSONField(default=list)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tisp_api_response_cache"
        constraints = (
            models.UniqueConstraint(
                fields=("endpoint", "params_hash"),
                name="uniq_tisp_api_response_cache_request",
            ),
        )
        indexes = (
            models.Index(fields=("endpoint", "params_hash")),
            models.Index(fields=("fetched_at",)),
        )

    def __str__(self):
        return f"{self.endpoint}:{self.params_hash}"


class TispDataValue(models.Model):
    datavaluekey = models.BigIntegerField(unique=True)
    area_level = models.CharField(max_length=20, blank=True)
    area_code = models.CharField(max_length=50, blank=True)
    parent_code = models.CharField(max_length=50, blank=True)
    area_name = models.CharField(max_length=255)
    tag = models.IntegerField(default=0)
    areakey = models.BigIntegerField(null=True, blank=True)
    indicatorkey = models.BigIntegerField()
    indicator_name = models.CharField(max_length=500)
    datavalue = models.FloatField(null=True, blank=True)
    time_name = models.CharField(max_length=100, blank=True)
    source_name = models.CharField(max_length=500, blank=True)
    source_mda = models.CharField(max_length=255, blank=True)
    source_link = models.URLField(blank=True)
    timeperiod_name = models.CharField(max_length=120, blank=True)
    subgroupkey = models.BigIntegerField(null=True, blank=True)
    timeperiodkey = models.BigIntegerField(null=True, blank=True)
    subgroup_name = models.CharField(max_length=255, blank=True)
    subgroup_code = models.CharField(max_length=255, blank=True)
    raw = models.JSONField(default=dict)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tisp_data_values"
        indexes = (
            models.Index(fields=("indicatorkey", "timeperiodkey", "subgroupkey")),
            models.Index(fields=("indicator_name",)),
            models.Index(fields=("area_name",)),
            models.Index(fields=("time_name",)),
            models.Index(fields=("fetched_at",)),
        )

    def __str__(self):
        return f"{self.indicator_name} - {self.area_name} - {self.time_name}"
