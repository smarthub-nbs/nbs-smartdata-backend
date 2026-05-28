import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models



class CustomUserManager(UserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The email field must be set.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "roles"
        ordering = ("name",)
        verbose_name = "Role"
        verbose_name_plural = "Roles"

    def __str__(self):
        return self.name


class Permission(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "permissions"
        ordering = ("name",)
        verbose_name = "Permission"
        verbose_name_plural = "Permissions"

    def __str__(self):
        return self.name


class UserRole(models.Model):
    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="user_roles",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="user_roles",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_roles"
        ordering = ("-assigned_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "role"), name="unique_user_role")
        ]
        verbose_name = "User Role"
        verbose_name_plural = "User Roles"

    def __str__(self):
        return f"{self.user.email} -> {self.role.code}"


class RolePermission(models.Model):
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "role_permissions"
        ordering = ("-assigned_at",)
        constraints = [
            models.UniqueConstraint(fields=("role", "permission"), name="unique_role_permission")
        ]
        verbose_name = "Role Permission"
        verbose_name_plural = "Role Permissions"

    def __str__(self):
        return f"{self.role.code} -> {self.permission.code}"


class User(AbstractUser):
    username = None

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    is_verified = models.BooleanField(default=False)
    last_login_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    def role_codes(self):
        return list(
            self.user_roles.select_related("role").values_list("role__code", flat=True)
        )

    def has_role(self, *role_codes):
        if not role_codes:
            return False
        return self.user_roles.filter(
            role__code__in=role_codes,
            role__is_active=True,
        ).exists()

    def _role_permissions(self):
        return {
            permission.code
            for permission in Permission.objects.filter(
                role_permissions__role__user_roles__user=self,
                role_permissions__role__is_active=True,
                role_permissions__permission__is_active=True,
            ).distinct()
        }

    def get_all_permissions(self, obj=None):
        return super().get_all_permissions(obj) | self._role_permissions()

    def has_perm(self, perm, obj=None):
        if self.is_active and self.is_superuser:
            return True
        return perm in self.get_all_permissions(obj)

    def has_module_perms(self, app_label):
        if self.is_active and self.is_superuser:
            return True
        return any(
            permission.startswith(f"{app_label}.")
            for permission in self.get_all_permissions()
        )

    def __str__(self):
        return f"{self.full_name} ({self.email})" if self.full_name else self.email
