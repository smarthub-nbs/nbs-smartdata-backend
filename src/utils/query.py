import uuid

from django.db.models import Q


def build_identifier_filter(id_field, slug_field, raw_value):
    try:
        parsed = uuid.UUID(str(raw_value))
    except (TypeError, ValueError, AttributeError):
        return Q(**{slug_field: raw_value})
    return Q(**{id_field: parsed}) | Q(**{slug_field: raw_value})
