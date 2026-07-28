from drf_spectacular.utils import OpenApiResponse, inline_serializer
from rest_framework import serializers


class ValidationErrorDetailsSerializer(serializers.Serializer):
    fields = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=False,
        default=dict,
        help_text="Field-level validation errors keyed by request field name.",
    )
    non_field_errors = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Validation errors not tied to a single field.",
    )


def _schema_component(component):
    if component is None:
        return serializers.JSONField(required=False, allow_null=True)

    if isinstance(component, (serializers.BaseSerializer, serializers.Field)):
        return component

    if isinstance(component, type) and issubclass(component, serializers.Serializer):
        return component()

    raise TypeError(f"Unsupported schema component: {component!r}")


def success_response_schema(
    name,
    data=None,
    description="Successful response.",
    **_kwargs,
):
    return OpenApiResponse(
        response=inline_serializer(
            name=name,
            fields={
                "success": serializers.BooleanField(default=True),
                "message": serializers.CharField(),
                "data": _schema_component(data),
            },
        ),
        description=description,
    )


def error_response_schema(name, description="Request failed."):
    return OpenApiResponse(
        response=inline_serializer(
            name=name,
            fields={
                "success": serializers.BooleanField(default=False),
                "error": inline_serializer(
                    name=f"{name}Body",
                    fields={
                        "code": serializers.CharField(),
                        "message": serializers.CharField(),
                        "request_id": serializers.CharField(
                            required=False,
                            allow_null=True,
                        ),
                        "details": serializers.JSONField(
                            required=False,
                            allow_null=True,
                        ),
                    },
                ),
            },
        ),
        description=description,
    )


def validation_error_response_schema(name, description="Validation failed."):
    return OpenApiResponse(
        response=inline_serializer(
            name=name,
            fields={
                "success": serializers.BooleanField(default=False),
                "error": inline_serializer(
                    name=f"{name}Body",
                    fields={
                        "code": serializers.CharField(default="validation_error"),
                        "message": serializers.CharField(default="Validation failed."),
                        "request_id": serializers.CharField(
                            required=False,
                            allow_null=True,
                        ),
                        "details": ValidationErrorDetailsSerializer(),
                    },
                ),
            },
        ),
        description=description,
    )


def standard_error_responses(
    prefix,
    *,
    include_400=False,
    include_401=False,
    include_403=False,
    include_404=False,
    include_409=False,
):
    responses = {}

    if include_400:
        responses[400] = validation_error_response_schema(
            f"{prefix}ValidationErrorResponse",
        )
    if include_401:
        responses[401] = error_response_schema(
            f"{prefix}UnauthorizedErrorResponse",
            description="Authentication is required or the JWT bearer token is invalid.",
        )
    if include_403:
        responses[403] = error_response_schema(
            f"{prefix}ForbiddenErrorResponse",
            description="The authenticated user does not have permission to perform this action.",
        )
    if include_404:
        responses[404] = error_response_schema(
            f"{prefix}NotFoundErrorResponse",
            description="The requested resource was not found.",
        )
    if include_409:
        responses[409] = error_response_schema(
            f"{prefix}ConflictErrorResponse",
            description="The request conflicts with related data or protected references.",
        )

    return responses
