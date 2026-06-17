from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from ..models import User


def get_tokens_for_user(user):
    refresh = TokenObtainPairSerializer.get_token(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


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

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        tokens = get_tokens_for_user(user)
        user.access = tokens["access"]
        user.refresh = tokens["refresh"]
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


class StatusResponseSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)
    scope = serializers.CharField(read_only=True)
