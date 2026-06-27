from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiRequest, inline_serializer
from rest_framework import serializers

from djapps.datasets.models import DatasetFrequency, DatasetStatus
from djapps.datasets.serializers import DatasetAdminQueueItemSerializer, DatasetFileSerializer


DATASET_ID_PARAMETER = OpenApiParameter(
    name="dataset_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="Dataset UUID.",
)

DATASET_SEARCH_PARAMETER = OpenApiParameter(
    name="q",
    type=str,
    location=OpenApiParameter.QUERY,
    description="Free-text search across slug, metadata, category, and tag fields.",
)

DATASET_STATUS_PARAMETER = OpenApiParameter(
    name="status",
    type=str,
    enum=[choice[0] for choice in DatasetStatus.CHOICES],
    location=OpenApiParameter.QUERY,
    description="Filter by dataset workflow status. Applied only for dataset admins.",
)

DATASET_PAGE_PARAMETER = OpenApiParameter(
    name="page",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description="Page number.",
)

DATASET_PAGE_SIZE_PARAMETER = OpenApiParameter(
    name="page_size",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description="Number of items per page. Maximum 100.",
)

DATASET_LIST_PARAMETERS = [
    DATASET_SEARCH_PARAMETER,
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
        description="Filter by file format such as csv, json, pdf, xls, or xlsx.",
    ),
    DATASET_STATUS_PARAMETER,
]

DATASET_ADMIN_QUEUE_PARAMETERS = [
    DATASET_SEARCH_PARAMETER,
    DATASET_STATUS_PARAMETER,
    DATASET_PAGE_PARAMETER,
    DATASET_PAGE_SIZE_PARAMETER,
]

DATASET_ADMIN_QUEUE_PAYLOAD = inline_serializer(
    name="DatasetAdminQueuePayload",
    fields={
        "items": DatasetAdminQueueItemSerializer(many=True),
        "pagination": inline_serializer(
            name="DatasetAdminQueuePagination",
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

DATASET_FILE_UPLOAD_REQUEST = OpenApiRequest(
    request=DatasetFileSerializer,
    encoding={"file": {"contentType": "*/*"}},
)

DATASET_FILE_UPLOAD_DESCRIPTION = (
    "Upload a dataset file using multipart form data. "
    f"Allowed extensions: {', '.join(settings.DATASET_ALLOWED_FILE_EXTENSIONS)}. "
    f"Maximum size: {settings.DATASET_MAX_UPLOAD_SIZE // (1024 * 1024)} MB."
)
