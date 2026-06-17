import uuid

from django.conf import settings
from django.db import models
from models import AllObjectsManager, BaseModel, SoftDeleteManager


class DatasetStatus:
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"

    CHOICES = (
        (DRAFT, "Draft"),
        (IN_REVIEW, "In Review"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
        (PUBLISHED, "Published"),
    )


class FileValidationStatus:
    VALIDATED = "validated"
    REJECTED = "rejected"

    CHOICES = (
        (VALIDATED, "Validated"),
        (REJECTED, "Rejected"),
    )


class DatasetFrequency:
    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"

    CHOICES = (
        (ANNUAL, "Annual"),
        (QUARTERLY, "Quarterly"),
        (MONTHLY, "Monthly"),
    )

class Category(BaseModel):
    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    name = models.CharField(max_length=50)
    slug = models.CharField(max_length=50)
    
    class Meta:
        db_table = "category"
        verbose_name = "Category"
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

    
class Dataset(BaseModel):
    soft_delete_enabled = True
    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    publisher_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    slug = models.CharField(max_length=50, unique=True)
    status = models.CharField(
        max_length=20,
        choices=DatasetStatus.CHOICES,
        default=DatasetStatus.DRAFT,
    )
    visibility = models.BooleanField(default=False)
    published_at = models.DateTimeField(blank=True, null=True)
    
    
    class Meta:
        db_table = 'datasets'
        verbose_name = 'Dataset'
        verbose_name_plural = 'Datasets'
        base_manager_name = "all_objects"
        default_manager_name = "objects"
        permissions = (
            ("review_dataset", "Can review dataset"),
            ("publish_dataset", "Can publish dataset"),
            ("view_all_dataset", "Can view all datasets"),
        )

    def __str__(self):
        return self.slug

class DatasetVersion(BaseModel):

    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='versions')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    version_number = models.CharField(max_length=20)
    changelog = models.TextField(blank=True)
    
    class Meta:
        db_table = 'dataset_versions'
        verbose_name = 'Dataset Version'
        verbose_name_plural = 'Dataset Versions'

    def __str__(self):
        return f"{self.dataset.slug} - v{self.version_number}"

class DatasetFile(BaseModel):

    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    dataset_version = models.ForeignKey(DatasetVersion, on_delete=models.CASCADE, related_name='files')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    file = models.FileField(upload_to='dataset_files/')
    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    file_format = models.CharField(max_length=50)
    checksum = models.CharField(max_length=64)
    is_primary = models.BooleanField(default=False)
    validation_status = models.CharField(
        max_length=20,
        choices=FileValidationStatus.CHOICES,
        default=FileValidationStatus.VALIDATED,
    )
    validated_at = models.DateTimeField(blank=True, null=True)
    validation_notes = models.TextField(blank=True)
    is_safe = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'dataset_files'
        verbose_name = 'Dataset File'
        verbose_name_plural = 'Dataset Files'

    def __str__(self):
        return self.filename
    
    
class Tag(BaseModel):
    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    name = models.CharField(max_length=50)
    slug = models.CharField(max_length=50)
    
    class Meta:
        db_table = 'tags'
        verbose_name = 'Tag'
        verbose_name_plural = 'Tags'

    def __str__(self):
        return self.name

class DatasetTag(BaseModel):
    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='dataset_tags')
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='tag_datasets')
    
    class Meta:
        db_table = 'dataset_tags'
        verbose_name = 'Dataset Tag'
        verbose_name_plural = 'Dataset Tags'

    def __str__(self):
        return f"{self.dataset.slug} - {self.tag.name}"
    
class DatasetStatusHistory(BaseModel):
    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='status_history')
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    reason = models.TextField()
    changed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'dataset_status_history'
        verbose_name = 'Dataset Status History'
        verbose_name_plural = 'Dataset Status Histories'

    def __str__(self):
        return f"{self.dataset.slug}: {self.old_status} -> {self.new_status} at {self.changed_at}"

class DatasetMetadata(BaseModel):
    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='metadata')
    title = models.CharField(max_length=100)
    description = models.TextField()
    license = models.CharField(max_length=100, blank=True, null=True)
    frequency = models.CharField(max_length=20, choices=DatasetFrequency.CHOICES, blank=True)
    region = models.CharField(max_length=100, blank=True)
    year = models.PositiveIntegerField(blank=True, null=True)
    publisher_name = models.CharField(max_length=255, blank=True)
    
    class Meta:
        db_table = 'dataset_metadata'
        verbose_name = 'Dataset Metadata'
        verbose_name_plural = 'Dataset Metadata'

    def __str__(self):
        return f"{self.dataset.slug} - {self.title}: {self.description}"
    
class IndexingStatus(BaseModel):
    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='indexing_status')
    indexed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20)
    details = models.TextField(blank=True)
    
    class Meta:
        db_table = 'indexing_status'
        verbose_name = 'Indexing Status'
        verbose_name_plural = 'Indexing Statuses'

    def __str__(self):
        return f"{self.dataset.slug} - {self.status} at {self.indexed_at}"


class DatasetAuditLog(BaseModel):
    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="audit_logs")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    action = models.CharField(max_length=50)
    target_model = models.CharField(max_length=100)
    target_id = models.UUIDField(blank=True, null=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "dataset_audit_logs"
        verbose_name = "Dataset Audit Log"
        verbose_name_plural = "Dataset Audit Logs"

    def __str__(self):
        return f"{self.dataset.slug} - {self.action} at {self.created_at}"
