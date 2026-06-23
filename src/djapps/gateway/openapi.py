from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, inline_serializer
from rest_framework import serializers

from djapps.datasets.models import DatasetFrequency
from djapps.gateway.serializers import (
    APIKeyDetailSerializer,
    APIUsageLogSerializer,
    GatewayDatasetChangeSerializer,
    OpenDatasetSerializer,
)


GATEWAY_DATASET_LOOKUP_PARAMETER = OpenApiParameter(
    name="dataset_lookup",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    description="Dataset UUID or slug.",
)

GATEWAY_FILE_ID_PARAMETER = OpenApiParameter(
    name="file_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="Dataset file UUID.",
)

GATEWAY_VERSION_ID_PARAMETER = OpenApiParameter(
    name="version_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="Dataset version UUID.",
)

API_KEY_HEADER_PARAMETER = OpenApiParameter(
    name="X-API-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Active API key used to access gateway endpoints.",
)

GATEWAY_UPDATED_SINCE_PARAMETER = OpenApiParameter(
    name="updated_since",
    type=OpenApiTypes.DATETIME,
    location=OpenApiParameter.QUERY,
    description="Return datasets changed on or after this ISO 8601 timestamp.",
)

GATEWAY_DATASET_LIST_PARAMETERS = [
    OpenApiParameter(
        name="q",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Free-text search across slug, metadata, category, and tag fields.",
    ),
    OpenApiParameter(
        name="category",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Filter by category UUID or category slug.",
    ),
    OpenApiParameter(
        name="tag",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Filter by tag UUID or tag slug.",
    ),
    OpenApiParameter(
        name="region",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Filter by metadata region.",
    ),
    OpenApiParameter(
        name="year",
        type=OpenApiTypes.INT,
        location=OpenApiParameter.QUERY,
        description="Filter by metadata year.",
    ),
    OpenApiParameter(
        name="license",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Filter by metadata license value.",
    ),
    OpenApiParameter(
        name="frequency",
        type=str,
        enum=[choice[0] for choice in DatasetFrequency.CHOICES],
        location=OpenApiParameter.QUERY,
        description="Filter by metadata update frequency.",
    ),
    OpenApiParameter(
        name="publisher",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Filter by metadata publisher name.",
    ),
    OpenApiParameter(
        name="file_format",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Filter by validated safe file format such as csv, json, pdf, xls, or xlsx.",
    ),
    OpenApiParameter(
        name="page",
        type=OpenApiTypes.INT,
        location=OpenApiParameter.QUERY,
        description="Page number.",
    ),
    OpenApiParameter(
        name="page_size",
        type=OpenApiTypes.INT,
        location=OpenApiParameter.QUERY,
        description="Number of items per page. Maximum 100.",
    ),
    GATEWAY_UPDATED_SINCE_PARAMETER,
]

GATEWAY_DATASET_LIST_PAYLOAD = inline_serializer(
    name="GatewayDatasetListPayload",
    fields={
        "items": OpenDatasetSerializer(many=True),
        "pagination": inline_serializer(
            name="GatewayDatasetPagination",
            fields={
                "page": serializers.IntegerField(),
                "page_size": serializers.IntegerField(),
                "total_pages": serializers.IntegerField(),
                "total_items": serializers.IntegerField(),
                "has_next": serializers.BooleanField(),
                "has_previous": serializers.BooleanField(),
                "next": serializers.CharField(allow_null=True),
                "previous": serializers.CharField(allow_null=True),
            },
        ),
    },
)

DEVELOPER_API_KEY_LIST_PAYLOAD = inline_serializer(
    name="DeveloperAPIKeyListPayload",
    fields={
        "items": APIKeyDetailSerializer(many=True),
        "pagination": inline_serializer(
            name="DeveloperAPIKeyListPagination",
            fields={
                "page": serializers.IntegerField(),
                "page_size": serializers.IntegerField(),
                "total_pages": serializers.IntegerField(),
                "total_items": serializers.IntegerField(),
                "has_next": serializers.BooleanField(),
                "has_previous": serializers.BooleanField(),
                "next": serializers.CharField(allow_null=True),
                "previous": serializers.CharField(allow_null=True),
            },
        ),
    },
)

DEVELOPER_API_USAGE_LIST_PAYLOAD = inline_serializer(
    name="DeveloperAPIUsageListPayload",
    fields={
        "items": APIUsageLogSerializer(many=True),
        "pagination": inline_serializer(
            name="DeveloperAPIUsageListPagination",
            fields={
                "page": serializers.IntegerField(),
                "page_size": serializers.IntegerField(),
                "total_pages": serializers.IntegerField(),
                "total_items": serializers.IntegerField(),
                "has_next": serializers.BooleanField(),
                "has_previous": serializers.BooleanField(),
                "next": serializers.CharField(allow_null=True),
                "previous": serializers.CharField(allow_null=True),
            },
        ),
    },
)

GATEWAY_DATASET_CHANGE_LIST_PAYLOAD = inline_serializer(
    name="GatewayDatasetChangeListPayload",
    fields={
        "items": GatewayDatasetChangeSerializer(many=True),
        "pagination": inline_serializer(
            name="GatewayDatasetChangePagination",
            fields={
                "page": serializers.IntegerField(),
                "page_size": serializers.IntegerField(),
                "total_pages": serializers.IntegerField(),
                "total_items": serializers.IntegerField(),
                "has_next": serializers.BooleanField(),
                "has_previous": serializers.BooleanField(),
                "next": serializers.CharField(allow_null=True),
                "previous": serializers.CharField(allow_null=True),
            },
        ),
    },
)
