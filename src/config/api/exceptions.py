from django.db.models.deletion import ProtectedError
from rest_framework import status
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler


def _stringify_error_detail(detail):
    if isinstance(detail, ErrorDetail):
        return str(detail)
    if isinstance(detail, dict):
        return {key: _stringify_error_detail(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [_stringify_error_detail(item) for item in detail]
    return detail


def _normalize_validation_details(detail):
    normalized = _stringify_error_detail(detail)
    non_field_key = api_settings.NON_FIELD_ERRORS_KEY

    if isinstance(normalized, dict):
        return {
            "fields": {
                key: value for key, value in normalized.items() if key != non_field_key
            },
            "non_field_errors": normalized.get(non_field_key, []),
        }

    if isinstance(normalized, list):
        return {
            "fields": {},
            "non_field_errors": normalized,
        }

    return {
        "fields": {},
        "non_field_errors": [normalized],
    }


def _build_error_payload(code, message, request_id=None, details=None):
    error = {
        "code": code,
        "message": message,
    }
    if request_id:
        error["request_id"] = request_id
    if details is not None:
        error["details"] = details

    return {
        "success": False,
        "error": error,
    }


def standardized_exception_handler(exc, context):
    response = exception_handler(exc, context)
    request = context.get("request")
    request_id = getattr(request, "request_id", None)

    if isinstance(exc, ValidationError):
        details = _normalize_validation_details(exc.detail)
        return response.__class__(
            _build_error_payload(
                code="validation_error",
                message="Validation failed.",
                request_id=request_id,
                details=details,
            ),
            status=response.status_code,
            headers=response.headers,
        )

    if isinstance(exc, ProtectedError):
        return Response(
            _build_error_payload(
                code="protected_resource",
                message="This resource cannot be deleted because other records depend on it.",
                request_id=request_id,
                details={
                    "fields": {},
                    "non_field_errors": [str(exc)],
                },
            ),
            status=status.HTTP_409_CONFLICT,
        )

    if response is None:
        return Response(
            _build_error_payload(
                code="server_error",
                message="An unexpected error occurred.",
                request_id=request_id,
            ),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    normalized = _stringify_error_detail(response.data)
    details = None
    message = "Request failed."

    if isinstance(normalized, dict):
        detail = normalized.get("detail")
        if detail:
            message = detail
        details = {key: value for key, value in normalized.items() if key != "detail"} or None
    elif isinstance(normalized, list):
        details = {"non_field_errors": normalized}
        message = "Request failed."
    elif normalized:
        message = normalized

    code = getattr(exc, "default_code", None) or f"http_{response.status_code}"
    return response.__class__(
        _build_error_payload(
            code=str(code),
            message=message,
            request_id=request_id,
            details=details,
        ),
        status=response.status_code,
        headers=response.headers,
    )
