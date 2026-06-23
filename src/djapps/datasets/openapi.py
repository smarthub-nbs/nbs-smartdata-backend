from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiRequest

from djapps.datasets.models import DatasetFrequency, DatasetStatus
from djapps.datasets.serializers import DatasetFileSerializer


DATASET_ID_PARAMETER = OpenApiParameter(
    name="dataset_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="Dataset UUID.",
)

DATASET_LIST_PARAMETERS = [
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
        description="Filter by file format such as csv, json, pdf, xls, or xlsx.",
    ),
    OpenApiParameter(
        name="status",
        type=str,
        enum=[choice[0] for choice in DatasetStatus.CHOICES],
        location=OpenApiParameter.QUERY,
        description="Filter by dataset workflow status. Applied only for dataset admins.",
    ),
]

DATASET_FILE_UPLOAD_REQUEST = OpenApiRequest(
    request=DatasetFileSerializer,
    encoding={"file": {"contentType": "*/*"}},
)

DATASET_FILE_UPLOAD_DESCRIPTION = (
    "Upload a dataset file using multipart form data. "
    f"Allowed extensions: {', '.join(settings.DATASET_ALLOWED_FILE_EXTENSIONS)}. "
    f"Maximum size: {settings.DATASET_MAX_UPLOAD_SIZE // (1024 * 1024)} MB."
)
