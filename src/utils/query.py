import uuid

from django.db.models import Q
from rest_framework.exceptions import ValidationError


def build_identifier_filter(id_field, slug_field, raw_value):
    try:
        parsed = uuid.UUID(str(raw_value))
    except (TypeError, ValueError, AttributeError):
        return Q(**{slug_field: raw_value})
    return Q(**{id_field: parsed}) | Q(**{slug_field: raw_value})


def parse_optional_bool(raw_value, field_name):
    if raw_value in (None, ""):
        return None

    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "false", "f", "no", "n"}:
        return False

    raise ValidationError({field_name: ["Enter a valid boolean value."]})
