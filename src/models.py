import uuid

from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        return self.filter(deleted_at__isnull=False)

    def delete(self):
        now = timezone.now()
        updated_count = self.alive().update(deleted_at=now, updated_at=now)
        return updated_count, {self.model._meta.label: updated_count}

    def hard_delete(self):
        return super().delete()

    def restore(self):
        now = timezone.now()
        updated_count = self.deleted().update(deleted_at=None, updated_at=now)
        return updated_count, {self.model._meta.label: updated_count}


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    def get_queryset(self):
        return super().get_queryset().alive()


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    pass


class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True,editable=False,default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    soft_delete_enabled = False

    class Meta:
        abstract = True
        verbose_name = ("")
        verbose_name_plural = ("s")

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def soft_delete(self, using=None):
        if self.deleted_at is not None:
            return 0, {self._meta.label: 0}

        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at", "updated_at"])
        return 1, {self._meta.label: 1}

    def restore(self, using=None):
        if self.deleted_at is None:
            return 0, {self._meta.label: 0}

        self.deleted_at = None
        self.save(using=using, update_fields=["deleted_at", "updated_at"])
        return 1, {self._meta.label: 1}

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def delete(self, using=None, keep_parents=False, hard=False):
        if hard or not self.soft_delete_enabled:
            return super().delete(using=using, keep_parents=keep_parents)
        return self.soft_delete(using=using)

    def __str__(self):
        pass
