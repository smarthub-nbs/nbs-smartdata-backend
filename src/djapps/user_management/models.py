import uuid

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from models import BaseModel


class CustomUserManager(UserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The email field must be set.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password is None:
            user.set_unusable_password()
        else:
            validate_password(password, user)
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self._create_user(email, password, **extra_fields)
        from .roles import ensure_default_user_group

        ensure_default_user_group(user)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser, BaseModel):
    username = None

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    is_verified = models.BooleanField(default=False)
    last_login_at = models.DateTimeField(blank=True, null=True)
    token_version = models.PositiveIntegerField(default=0)


    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def role_names(self):
        return list(self.groups.values_list("name", flat=True))

    @property
    def role_codes(self):
        return self.role_names

    def has_role(self, *role_names):
        if not role_names:
            return False
        return self.groups.filter(name__in=role_names).exists()

    def __str__(self):
        return f"{self.full_name} ({self.email})" if self.full_name else self.email
