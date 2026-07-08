from django.db import models
from django.conf import settings

from models import BaseModel


class APIConsumer(BaseModel):
    CONSUMER_TYPES = [
        ("developer", "Developer"),
        ("researcher", "Researcher"),
        ("institution", "Institution"),
        ("internal_system", "Internal System"),
    ]

    STATUS_CHOICES = [
        ("active", "Active"),
        ("suspended", "Suspended"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="api_consumers"
    )
    name = models.CharField(max_length=255)
    consumer_type = models.CharField(max_length=50, choices=CONSUMER_TYPES)
    organization_name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="active")

    class Meta:
        db_table = 'api_consumer'
        verbose_name = "APIConsumer"
        verbose_name_plural = "APIConsumers"
        indexes = [
            models.Index(fields=["status", "-created_at"], name="api_consumer_status_idx"),
            models.Index(fields=["consumer_type", "-created_at"], name="api_consumer_type_idx"),
        ]
    
    def __str__(self):
        return self.name



class APIScope(BaseModel):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = "api_scope"
        verbose_name = "APIScope"
        verbose_name_plural = "APIScopes"
        indexes = [
            models.Index(fields=["is_active", "code"], name="api_scope_active_idx"),
        ]

    def __str__(self):
        return f'{self.name} - {self.code}'


class APIKey(BaseModel):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("revoked", "Revoked"),
        ("expired", "Expired"),
    ]

    consumer = models.ForeignKey(
        APIConsumer,
        on_delete=models.PROTECT,
        related_name="api_keys"
    )
    name = models.CharField(max_length=255)
    prefix = models.CharField(max_length=20, db_index=True)
    hashed_key = models.CharField(max_length=255)
    scopes = models.ManyToManyField(APIScope, through="APIKeyScope")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="active")
    expires_at = models.DateTimeField(blank=True, null=True)
    last_used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        db_table = "api_key"
        verbose_name = "APIKey"
        verbose_name_plural = "APIKeys"
        indexes = [
            models.Index(fields=["consumer", "status"], name="api_key_consumer_status_idx"),
            models.Index(fields=["status", "-created_at"], name="api_key_status_idx"),
            models.Index(fields=["-last_used_at"], name="api_key_last_used_idx"),
        ]
        
    def __str__(self):
        return self.name
    



class APIKeyScope(BaseModel):
    api_key = models.ForeignKey(APIKey, on_delete=models.PROTECT)
    scope = models.ForeignKey(APIScope, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("api_key", "scope")
        db_table = "api_key_scope"
        verbose_name = "APIKeyScope"
        verbose_name_plural = "APIKeyScopes"
        indexes = [
            models.Index(fields=["api_key", "scope"], name="api_key_scope_lookup_idx"),
        ]
        
    def __str__(self):
        return f"{self.api_key.name} - {self.scope.code}"
        


class APIUsageLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    api_key = models.ForeignKey(
        APIKey,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    consumer = models.ForeignKey(
        APIConsumer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    endpoint = models.CharField(max_length=255)
    method = models.CharField(max_length=20)
    status_code = models.IntegerField()
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    dataset_id = models.UUIDField(blank=True, null=True)
    response_time_ms = models.PositiveIntegerField(blank=True, null=True)
    error_code = models.CharField(max_length=100, blank=True, null=True)
    
    class Meta:
        db_table = "api_usage_log"
        verbose_name = "APIUsageLog"
        verbose_name_plural = "APIUsageLogs"
        indexes = [
            models.Index(fields=["created_at"], name="api_usage_created_idx"),
            models.Index(fields=["api_key", "-created_at"], name="api_usage_key_idx"),
            models.Index(fields=["consumer", "-created_at"], name="api_usage_consumer_idx"),
            models.Index(fields=["endpoint", "method"], name="api_usage_endpoint_idx"),
            models.Index(fields=["dataset_id", "-created_at"], name="api_usage_dataset_idx"),
        ]

    def __str__(self):
        return f"{self.method} {self.endpoint} ({self.status_code})"
