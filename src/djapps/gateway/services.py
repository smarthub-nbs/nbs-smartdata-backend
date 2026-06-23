import secrets
from dataclasses import dataclass

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import APIConsumer, APIKey


DEFAULT_API_KEY_PREFIX = "smartdata_"
DEFAULT_API_KEY_PREFIX_LENGTH = 20
DEFAULT_API_KEY_TOKEN_BYTES = 40


@dataclass(frozen=True)
class GeneratedAPIKey:
    raw_key: str
    prefix: str
    hashed_key: str


def hash_api_key(raw_key: str) -> str:
    return make_password(raw_key)


def verify_api_key(raw_key: str, hashed_key: str) -> bool:
    return check_password(raw_key, hashed_key)


def get_key_prefix(raw_key: str, *, prefix_length: int = DEFAULT_API_KEY_PREFIX_LENGTH) -> str:
    if prefix_length <= 0:
        raise ValueError("prefix_length must be greater than 0.")

    return raw_key[:prefix_length]


def generate_api_key(
    *,
    prefix_length: int = DEFAULT_API_KEY_PREFIX_LENGTH,
    token_bytes: int = DEFAULT_API_KEY_TOKEN_BYTES,
) -> GeneratedAPIKey:
    if prefix_length <= 0:
        raise ValueError("prefix_length must be greater than 0.")

    if token_bytes <= 0:
        raise ValueError("token_bytes must be greater than 0.")

    raw_key = f"{DEFAULT_API_KEY_PREFIX}{secrets.token_urlsafe(token_bytes)}"
    prefix = get_key_prefix(raw_key, prefix_length=prefix_length)

    return GeneratedAPIKey(
        raw_key=raw_key,
        prefix=prefix,
        hashed_key=hash_api_key(raw_key),
    )


def default_consumer_name_for_user(user) -> str:
    full_name = getattr(user, "full_name", "").strip()
    return full_name or user.email


def get_or_create_developer_consumer(
    user,
    *,
    consumer_name: str | None = None,
    organization_name: str | None = None,
) -> APIConsumer:
    resolved_name = (consumer_name or "").strip() or default_consumer_name_for_user(user)
    queryset = APIConsumer.objects.filter(
        user=user,
        consumer_type="developer",
        email=user.email,
        name=resolved_name,
    ).order_by("created_at")

    consumer = queryset.first()
    if consumer is not None:
        updated_fields = []
        if consumer.status != "active":
            consumer.status = "active"
            updated_fields.append("status")
        normalized_org = organization_name or None
        if normalized_org != consumer.organization_name:
            consumer.organization_name = normalized_org
            updated_fields.append("organization_name")
        if updated_fields:
            updated_fields.append("updated_at")
            consumer.save(update_fields=updated_fields)
        return consumer

    return APIConsumer.objects.create(
        user=user,
        name=resolved_name,
        consumer_type="developer",
        organization_name=organization_name or None,
        email=user.email,
        status="active",
    )


def issue_api_key(
    *,
    consumer: APIConsumer,
    name: str,
    expires_at=None,
) -> tuple[APIKey, str]:
    generated_key = generate_api_key()
    api_key = APIKey.objects.create(
        consumer=consumer,
        name=name,
        prefix=generated_key.prefix,
        hashed_key=generated_key.hashed_key,
        status="active",
        expires_at=expires_at,
    )
    return api_key, generated_key.raw_key


def regenerate_api_key(api_key: APIKey) -> tuple[APIKey, str]:
    generated_key = generate_api_key()
    api_key.prefix = generated_key.prefix
    api_key.hashed_key = generated_key.hashed_key
    api_key.status = "active"
    api_key.revoked_at = None
    api_key.last_used_at = None
    api_key.save(
        update_fields=[
            "prefix",
            "hashed_key",
            "status",
            "revoked_at",
            "last_used_at",
            "updated_at",
        ]
    )
    return api_key, generated_key.raw_key


def revoke_api_key(api_key: APIKey) -> APIKey:
    if api_key.status != "revoked" or api_key.revoked_at is None:
        api_key.status = "revoked"
        api_key.revoked_at = timezone.now()
        api_key.save(update_fields=["status", "revoked_at", "updated_at"])
    return api_key
