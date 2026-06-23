# apps/gateway/authentication.py

from django.db import connection
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.utils import timezone

from .models import APIKey
from .services import verify_api_key, get_key_prefix


class APIKeyAuthentication(BaseAuthentication):
    keyword = "X-API-Key"

    def authenticate_header(self, request):
        return self.keyword

    def api_key_tables_ready(self):
        required_tables = {
            APIKey._meta.db_table,
            APIKey._meta.get_field("consumer").remote_field.model._meta.db_table,
        }
        try:
            existing_tables = set(connection.introspection.table_names())
        except Exception:
            return False
        return required_tables.issubset(existing_tables)

    def authenticate(self, request):
        raw_key = request.headers.get("X-API-Key")

        if not raw_key:
            return None

        if not self.api_key_tables_ready():
            raise AuthenticationFailed("API key authentication is not configured.")

        prefix = get_key_prefix(raw_key)

        try:
            api_key = APIKey.objects.select_related("consumer").get(prefix=prefix)
        except APIKey.DoesNotExist:
            raise AuthenticationFailed("Invalid API key.")

        if not verify_api_key(raw_key, api_key.hashed_key):
            raise AuthenticationFailed("Invalid API key.")

        if api_key.status != "active":
            raise AuthenticationFailed("API key is not active.")

        if api_key.expires_at and api_key.expires_at < timezone.now():
            raise AuthenticationFailed("API key has expired.")

        if api_key.consumer.status != "active":
            raise AuthenticationFailed("API consumer is suspended.")

        api_key.last_used_at = timezone.now()
        api_key.save(update_fields=["last_used_at"])

        request.api_key = api_key
        request.api_consumer = api_key.consumer

        return None, api_key
