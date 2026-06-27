from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from ..models import User
from .accounts import mark_user_logged_in
from ..roles import sync_user_groups


def get_tokens_for_user(user):
    refresh = TokenObtainPairSerializer.get_token(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


def normalize_email_value(value):
    return User.objects.normalize_email(value).lower()


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        username_field = self.username_field
        if attrs.get(username_field):
            attrs[username_field] = normalize_email_value(attrs[username_field])

        data = super().validate(attrs)
        mark_user_logged_in(self.user)
        return data


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "password",
            "first_name",
            "last_name",
            "access",
            "refresh",
        )

    def validate_email(self, value):
        normalized = normalize_email_value(value)
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return normalized

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        tokens = get_tokens_for_user(user)
        user.access = tokens["access"]
        user.refresh = tokens["refresh"]
        mark_user_logged_in(user)
        return user


class CurrentUserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "is_verified",
            "is_staff",
            "is_superuser",
            "roles",
            "permissions",
        )

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_roles(self, obj):
        return list(obj.groups.values_list("name", flat=True))

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permissions(self, obj):
        return sorted(obj.get_all_permissions())


class SocialLoginSerializer(serializers.Serializer):
    access_token = serializers.CharField(write_only=True)
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    user = CurrentUserSerializer(read_only=True)


class GitHubOAuthCodeExchangeSerializer(serializers.Serializer):
    code = serializers.CharField(write_only=True)
    redirect_uri = serializers.URLField(write_only=True)
    code_verifier = serializers.CharField(write_only=True, min_length=43, max_length=128)
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    user = CurrentUserSerializer(read_only=True)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)


class TokenRefreshRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenRefreshResponseSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)


class SocialLoginResponseSerializer(serializers.Serializer):
    user = CurrentUserSerializer(read_only=True)
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class EmptyRequestSerializer(serializers.Serializer):
    pass


class StatusResponseSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)
    scope = serializers.CharField(read_only=True)


class ProfileUpdateSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=False)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")

    def validate_email(self, value):
        normalized = normalize_email_value(value)
        queryset = User.objects.filter(email__iexact=normalized)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return normalized

    def update(self, instance, validated_data):
        email = validated_data.get("email")
        if email and email != instance.email:
            instance.email = email
            instance.is_verified = False

        for field in ("first_name", "last_name"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        update_fields = list(validated_data.keys())
        if "email" in validated_data and "is_verified" not in update_fields:
            update_fields.append("is_verified")
        instance.save(update_fields=list(dict.fromkeys(update_fields)))
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return normalize_email_value(value)


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class EmailVerificationConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)


class GroupDetailSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ("id", "name", "permissions")

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permissions(self, obj):
        return sorted(
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in obj.permissions.all()
        )


class UserAdminListSerializer(serializers.ModelSerializer):
    groups = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "is_verified",
            "is_staff",
            "is_superuser",
            "groups",
            "created_at",
            "last_login",
            "last_login_at",
        )

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_groups(self, obj):
        return list(obj.groups.values_list("name", flat=True))


class UserAdminDetailSerializer(UserAdminListSerializer):
    permissions = serializers.SerializerMethodField()

    class Meta(UserAdminListSerializer.Meta):
        fields = UserAdminListSerializer.Meta.fields + ("permissions", "updated_at")

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permissions(self, obj):
        return sorted(obj.get_all_permissions())


class AdminUserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    groups = serializers.SlugRelatedField(
        slug_field="name",
        queryset=Group.objects.order_by("name"),
        many=True,
        required=False,
    )

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "first_name",
            "last_name",
            "is_active",
            "is_verified",
            "groups",
        )

    def validate_email(self, value):
        normalized = normalize_email_value(value)
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return normalized

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        groups = validated_data.pop("groups", [])
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        if groups:
            sync_user_groups(user, groups)
        return user


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=False)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "is_verified")

    def validate_email(self, value):
        normalized = normalize_email_value(value)
        queryset = User.objects.filter(email__iexact=normalized)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return normalized

    def update(self, instance, validated_data):
        email = validated_data.get("email")
        if email and email != instance.email and "is_verified" not in validated_data:
            validated_data["is_verified"] = False

        for attribute, value in validated_data.items():
            setattr(instance, attribute, value)

        instance.save(update_fields=list(validated_data.keys()))
        return instance


class UserGroupAssignmentSerializer(serializers.Serializer):
    groups = serializers.SlugRelatedField(
        slug_field="name",
        queryset=Group.objects.order_by("name"),
        many=True,
    )
