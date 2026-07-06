import json
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiRequest,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from config.api.responses import (
    StandardizedAPIView,
    StandardizedModelViewSet,
    StandardizedReadOnlyModelViewSet,
    success_response,
)
from config.api.schema import success_response_schema, standard_error_responses
from djapps.datasets.audit import log_dataset_event
from djapps.datasets.models import (
    Category,
    Dataset,
    DatasetAuditLog,
    DatasetBookmark,
    DatasetBulkActionJob,
    DatasetBulkActionJobStatus,
    DatasetBulkUploadJob,
    DatasetBulkUploadJobItem,
    DatasetBulkUploadJobStatus,
    DatasetFile,
    DatasetMetadata,
    DatasetStatus,
    DatasetStatusHistory,
    DatasetTag,
    DatasetVersion,
    FileValidationStatus,
    IndexingStatus,
    Region,
    Tag,
)
from djapps.datasets.helpers import (
    create_status_history,
    filter_related_queryset_by_dataset_access,
    request_audit_details,
    validate_dataset_ready_for_review,
)
from djapps.datasets.charting import build_dataset_chart_payload
from djapps.datasets.permissions import (
    CanAccessDataset,
    CanAccessDatasetRelatedObject,
    CanCreateDataset,
    CanPublishDataset,
    CanRestoreDataset,
    CanReviewDataset,
    CanViewDatasetAuditLog,
    can_change_dataset,
    can_view_dataset,
    get_dataset_from_object,
    has_dataset_admin_access,
)
from djapps.datasets.serializers import (
    CategorySerializer,
    DatasetAdminQueueItemSerializer,
    DatasetAdminQueueSummarySerializer,
    DatasetAdminBulkActionSerializer,
    DatasetAdminBulkActionJobSerializer,
    DatasetAdminBulkActionJobDetailSerializer,
    DatasetAdminBulkActionJobListPayloadSerializer,
    DatasetBulkUploadJobCreateSerializer,
    DatasetBulkUploadJobSerializer,
    DatasetBulkUploadJobDetailSerializer,
    DatasetBulkUploadJobListPayloadSerializer,
    DatasetAuditLogSerializer,
    DatasetBookmarkSerializer,
    DatasetBookmarkListPayloadSerializer,
    DatasetDetailSerializer,
    DatasetFileSerializer,
    DatasetFileDataQuerySerializer,
    DatasetFileChartQuerySerializer,
    DatasetFileChartResponseSerializer,
    DatasetFileDataResponseSerializer,
    DatasetFileValidateSerializer,
    DatasetMetadataSerializer,
    DatasetPublishSerializer,
    DatasetReviewSerializer,
    DatasetRestoreSerializer,
    DatasetSerializer,
    DatasetStatusHistorySerializer,
    DatasetSubmitReviewSerializer,
    DatasetTagSerializer,
    DatasetTransferOwnerSerializer,
    DatasetVersionSerializer,
    DatasetWriteSerializer,
    IndexingStatusSerializer,
    RegionSerializer,
    TagSerializer,
    inspect_dataset_file,
)
from djapps.datasets.openapi import (
    DATASET_ADMIN_QUEUE_PARAMETERS,
    DATASET_ADMIN_QUEUE_PAYLOAD,
    DATASET_FILE_CREATE_REQUEST,
    DATASET_FILE_UPLOAD_DESCRIPTION,
    DATASET_FILE_UPDATE_REQUEST,
    DATASET_ID_PARAMETER,
    DATASET_LIST_PARAMETERS,
)
from djapps.datasets.structured_data import build_structured_payload
from djapps.datasets.tasks import run_bulk_action_job
from djapps.datasets.tasks import run_bulk_upload_job
from djapps.user_management.api.permissions import HasPermission
from utils.pagination import CustomPagination
from utils.query import build_identifier_filter, parse_optional_bool


class PublicReadAdminWriteViewSet(StandardizedModelViewSet):
    permission_classes = (HasPermission,)

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        self.required_permissions = self.get_required_permissions()
        return [HasPermission()]

    def get_required_permissions(self):
        action_to_permission = {
            "create": "add",
            "update": "change",
            "partial_update": "change",
            "destroy": "delete",
        }
        permission_action = action_to_permission.get(self.action)
        if permission_action is None:
            return ()

        model = self.get_queryset().model
        return (
            f"{model._meta.app_label}.{permission_action}_{model._meta.model_name}",
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_category_list",
        summary="List dataset categories",
        description="Return the public taxonomy list of dataset categories.",
        auth=[],
        responses={
            200: success_response_schema(
                "CategoryListSuccessResponse",
                CategorySerializer(many=True),
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_category_retrieve",
        summary="Retrieve a dataset category",
        description="Return a single category by ID.",
        auth=[],
        responses={
            200: success_response_schema(
                "CategoryRetrieveSuccessResponse",
                CategorySerializer,
            ),
            **standard_error_responses(
                "CategoryRetrieve",
                include_404=True,
            ),
        },
    ),
    create=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_category_create",
        summary="Create a dataset category",
        description="Create a new dataset category. Admin access is required. If `slug` is omitted, it is generated automatically from `name`.",
        request=CategorySerializer,
        responses={
            201: success_response_schema(
                "CategoryCreateSuccessResponse",
                CategorySerializer,
            ),
            **standard_error_responses(
                "CategoryCreate",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    ),
    update=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_category_update",
        summary="Replace a dataset category",
        description="Update a category completely. Admin access is required.",
        request=CategorySerializer,
        responses={
            200: success_response_schema(
                "CategoryUpdateSuccessResponse",
                CategorySerializer,
            ),
            **standard_error_responses(
                "CategoryUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    partial_update=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_category_partial_update",
        summary="Partially update a dataset category",
        description="Update selected category fields. Admin access is required.",
        request=CategorySerializer,
        responses={
            200: success_response_schema(
                "CategoryPartialUpdateSuccessResponse",
                CategorySerializer,
            ),
            **standard_error_responses(
                "CategoryPartialUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    destroy=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_category_destroy",
        summary="Delete a dataset category",
        description="Delete a category. Categories referenced by datasets are protected from deletion.",
        responses={
            200: success_response_schema(
                "CategoryDestroySuccessResponse",
                description="Category deleted successfully.",
            ),
            **standard_error_responses(
                "CategoryDestroy",
                include_401=True,
                include_403=True,
                include_404=True,
                include_409=True,
            ),
        },
    ),
)
class CategoryView(PublicReadAdminWriteViewSet):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer


@extend_schema_view(
    list=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_tag_list",
        summary="List dataset tags",
        description="Return the public taxonomy list of dataset tags.",
        auth=[],
        responses={
            200: success_response_schema(
                "TagListSuccessResponse",
                TagSerializer(many=True),
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_tag_retrieve",
        summary="Retrieve a dataset tag",
        description="Return a single tag by ID.",
        auth=[],
        responses={
            200: success_response_schema(
                "TagRetrieveSuccessResponse",
                TagSerializer,
            ),
            **standard_error_responses(
                "TagRetrieve",
                include_404=True,
            ),
        },
    ),
    create=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_tag_create",
        summary="Create a dataset tag",
        description="Create a new dataset tag. Admin access is required. If `slug` is omitted, it is generated automatically from `name`.",
        request=TagSerializer,
        responses={
            201: success_response_schema(
                "TagCreateSuccessResponse",
                TagSerializer,
            ),
            **standard_error_responses(
                "TagCreate",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    ),
    update=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_tag_update",
        summary="Replace a dataset tag",
        description="Update a tag completely. Admin access is required.",
        request=TagSerializer,
        responses={
            200: success_response_schema(
                "TagUpdateSuccessResponse",
                TagSerializer,
            ),
            **standard_error_responses(
                "TagUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    partial_update=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_tag_partial_update",
        summary="Partially update a dataset tag",
        description="Update selected tag fields. Admin access is required.",
        request=TagSerializer,
        responses={
            200: success_response_schema(
                "TagPartialUpdateSuccessResponse",
                TagSerializer,
            ),
            **standard_error_responses(
                "TagPartialUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    destroy=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_tag_destroy",
        summary="Delete a dataset tag",
        description="Delete a dataset tag. Admin access is required.",
        responses={
            200: success_response_schema(
                "TagDestroySuccessResponse",
                description="Tag deleted successfully.",
            ),
            **standard_error_responses(
                "TagDestroy",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
)
class TagView(PublicReadAdminWriteViewSet):
    queryset = Tag.objects.all().order_by("name")
    serializer_class = TagSerializer


@extend_schema_view(
    list=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_region_list",
        summary="List dataset regions",
        description="Return the public taxonomy list of dataset regions.",
        auth=[],
        responses={
            200: success_response_schema(
                "RegionListSuccessResponse",
                RegionSerializer(many=True),
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_region_retrieve",
        summary="Retrieve a dataset region",
        description="Return a single region by ID.",
        auth=[],
        responses={
            200: success_response_schema(
                "RegionRetrieveSuccessResponse",
                RegionSerializer,
            ),
            **standard_error_responses(
                "RegionRetrieve",
                include_404=True,
            ),
        },
    ),
    create=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_region_create",
        summary="Create a dataset region",
        description="Create a new dataset region. Admin access is required.",
        request=RegionSerializer,
        responses={
            201: success_response_schema(
                "RegionCreateSuccessResponse",
                RegionSerializer,
            ),
            **standard_error_responses(
                "RegionCreate",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    ),
    update=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_region_update",
        summary="Replace a dataset region",
        description="Update a region completely. Admin access is required.",
        request=RegionSerializer,
        responses={
            200: success_response_schema(
                "RegionUpdateSuccessResponse",
                RegionSerializer,
            ),
            **standard_error_responses(
                "RegionUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    partial_update=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_region_partial_update",
        summary="Partially update a dataset region",
        description="Update selected region fields. Admin access is required.",
        request=RegionSerializer,
        responses={
            200: success_response_schema(
                "RegionPartialUpdateSuccessResponse",
                RegionSerializer,
            ),
            **standard_error_responses(
                "RegionPartialUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    destroy=extend_schema(
        tags=["Dataset Taxonomy"],
        operation_id="dataset_region_destroy",
        summary="Delete a dataset region",
        description="Delete a dataset region. Admin access is required.",
        responses={
            200: success_response_schema(
                "RegionDestroySuccessResponse",
                description="Region deleted successfully.",
            ),
            **standard_error_responses(
                "RegionDestroy",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
)
class RegionView(PublicReadAdminWriteViewSet):
    queryset = Region.objects.all().order_by("name")
    serializer_class = RegionSerializer


class DatasetBaseView(StandardizedAPIView):
    serializer_class = DatasetSerializer
    detail_serializer_class = DatasetDetailSerializer
    write_serializer_class = DatasetWriteSerializer
    pagination_class = CustomPagination

    def get_base_queryset(self):
        return Dataset.objects.select_related(
            "publisher_user",
            "category",
        ).prefetch_related(
            "metadata",
            "dataset_tags__tag",
            "versions__files",
        )

    def get_object(self):
        dataset = get_object_or_404(
            self.get_base_queryset(), pk=self.kwargs["dataset_id"]
        )
        self.check_object_permissions(self.request, dataset)
        return dataset

    def serialize_detail(self, dataset):
        return self.detail_serializer_class(dataset).data

    def paginate_queryset(self, queryset):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        return paginator, page

    def apply_dataset_search_filter(self, queryset, search):
        return queryset.filter(
            Q(slug__icontains=search)
            | Q(metadata__title__icontains=search)
            | Q(metadata__description__icontains=search)
            | Q(metadata__publisher_name__icontains=search)
            | Q(metadata__region__icontains=search)
            | Q(category__name__icontains=search)
            | Q(category__slug__icontains=search)
            | Q(dataset_tags__tag__name__icontains=search)
            | Q(dataset_tags__tag__slug__icontains=search)
        )

    def filter_dataset_queryset(self, queryset, *, allow_status_filter=False):
        params = self.request.query_params

        search = params.get("q")
        if search:
            queryset = self.apply_dataset_search_filter(queryset, search)

        category = params.get("category")
        if category:
            queryset = queryset.filter(
                build_identifier_filter(
                    "category__id", "category__slug__iexact", category
                )
            )

        tag = params.get("tag")
        if tag:
            queryset = queryset.filter(
                build_identifier_filter(
                    "dataset_tags__tag__id",
                    "dataset_tags__tag__slug__iexact",
                    tag,
                )
            )

        region = params.get("region")
        if region:
            queryset = queryset.filter(metadata__region__iexact=region)

        dataset_year = params.get("year")
        if dataset_year:
            queryset = queryset.filter(metadata__year=dataset_year)

        license_name = params.get("license")
        if license_name:
            queryset = queryset.filter(metadata__license__iexact=license_name)

        frequency = params.get("frequency")
        if frequency:
            queryset = queryset.filter(metadata__frequency__iexact=frequency)

        publisher = params.get("publisher")
        if publisher:
            queryset = queryset.filter(metadata__publisher_name__icontains=publisher)

        file_format = params.get("file_format")
        if file_format:
            queryset = queryset.filter(
                versions__files__file_format__iexact=file_format.lower()
            )

        if allow_status_filter and params.get("status"):
            queryset = queryset.filter(status=params["status"])

        return queryset


class DatasetView(DatasetBaseView):

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [CanCreateDataset()]

    def get_queryset(self):
        queryset = self.get_base_queryset()
        user = self.request.user

        if not user or not user.is_authenticated:
            queryset = queryset.filter(
                visibility=True,
                status=DatasetStatus.PUBLISHED,
            )
        elif has_dataset_admin_access(user):
            queryset = queryset
        else:
            queryset = queryset.filter(
                Q(visibility=True, status=DatasetStatus.PUBLISHED)
                | Q(publisher_user=user)
            )

        queryset = self.filter_dataset_queryset(
            queryset,
            allow_status_filter=has_dataset_admin_access(user),
        )
        return queryset.order_by("-published_at", "-created_at").distinct()

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_list",
        summary="List datasets",
        description=(
            "Return datasets visible to the caller. "
            "Anonymous users see published datasets only. "
            "Authenticated owners also see their own drafts and rejected datasets. "
            "Dataset admins can see all datasets."
        ),
        auth=[],
        parameters=DATASET_LIST_PARAMETERS,
        responses={
            200: success_response_schema(
                "DatasetListSuccessResponse",
                DatasetSerializer(many=True),
                description="Datasets returned successfully.",
            ),
        },
    )
    def get(self, request):
        serializer = self.serializer_class(self.get_queryset(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_create",
        summary="Create dataset draft",
        description="Create a new dataset in `draft` status. The authenticated user becomes the dataset publisher. If `slug` is omitted, it is generated automatically.",
        request=DatasetWriteSerializer,
        examples=[
            OpenApiExample(
                "Create Dataset Request",
                value={
                    "category": "11111111-1111-1111-1111-111111111111",
                },
                request_only=True,
            ),
        ],
        responses={
            201: success_response_schema(
                "DatasetCreateSuccessResponse",
                DatasetDetailSerializer,
                description="Dataset draft created successfully.",
            ),
            **standard_error_responses(
                "DatasetCreate",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def post(self, request):
        serializer = self.write_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        dataset = serializer.save(
            publisher_user=request.user,
            status=DatasetStatus.DRAFT,
            visibility=False,
            published_at=None,
        )
        log_dataset_event(
            dataset,
            "dataset_created",
            actor=request.user,
            details=request_audit_details(request, status=dataset.status),
        )
        return Response(
            self.serialize_detail(dataset),
            status=status.HTTP_201_CREATED,
        )


class DatasetAdminQueueView(DatasetBaseView):
    permission_classes = [HasPermission]
    required_permissions = (
        "datasets.view_all_dataset",
        "datasets.review_dataset",
    )
    serializer_class = DatasetAdminQueueItemSerializer

    def annotate_admin_queue_queryset(self, queryset):
        metadata_queryset = DatasetMetadata.objects.filter(
            dataset=OuterRef("pk"),
            deleted_at__isnull=True,
        ).order_by("-created_at", "-id")
        file_queryset = DatasetFile.objects.filter(
            dataset_version__dataset=OuterRef("pk"),
            dataset_version__deleted_at__isnull=True,
            deleted_at__isnull=True,
        ).order_by("-dataset_version__created_at", "-created_at", "-id")

        return queryset.annotate(
            title=Subquery(metadata_queryset.values("title")[:1]),
            has_metadata=Exists(metadata_queryset),
            has_tag=Exists(
                DatasetTag.objects.filter(
                    dataset=OuterRef("pk"),
                    deleted_at__isnull=True,
                )
            ),
            has_file=Exists(file_queryset),
            primary_file_id=Subquery(
                file_queryset.filter(is_primary=True).values("id")[:1]
            ),
        )

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_admin_queue",
        summary="List dataset admin queue",
        description=(
            "Return a paginated admin queue of datasets for review and workflow tracking. "
            "Only dataset administrators can access this endpoint."
        ),
        parameters=DATASET_ADMIN_QUEUE_PARAMETERS,
        responses={
            200: success_response_schema(
                "DatasetAdminQueueSuccessResponse",
                DATASET_ADMIN_QUEUE_PAYLOAD,
                description="Dataset admin queue returned successfully.",
            ),
            **standard_error_responses(
                "DatasetAdminQueue",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def get(self, request):
        queryset = (
            self.annotate_admin_queue_queryset(
                self.filter_dataset_queryset(
                    self.get_base_queryset(),
                    allow_status_filter=True,
                )
            )
            .order_by("-updated_at", "-created_at")
            .distinct()
        )
        paginator, page = self.paginate_queryset(queryset)
        serializer = self.serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class DatasetAdminQueueSummaryView(DatasetBaseView):
    permission_classes = [HasPermission]
    required_permissions = (
        "datasets.view_all_dataset",
        "datasets.review_dataset",
    )
    serializer_class = DatasetAdminQueueSummarySerializer

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_admin_queue_summary",
        summary="Get dataset admin queue summary",
        description=(
            "Return admin queue totals grouped by dataset workflow status. "
            "Only dataset administrators can access this endpoint."
        ),
        responses={
            200: success_response_schema(
                "DatasetAdminQueueSummarySuccessResponse",
                DatasetAdminQueueSummarySerializer,
                description="Dataset admin queue summary returned successfully.",
            ),
            **standard_error_responses(
                "DatasetAdminQueueSummary",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        summary = self.get_base_queryset().aggregate(
            total=Count("id"),
            draft=Count("id", filter=Q(status=DatasetStatus.DRAFT)),
            in_review=Count("id", filter=Q(status=DatasetStatus.IN_REVIEW)),
            approved=Count("id", filter=Q(status=DatasetStatus.APPROVED)),
            rejected=Count("id", filter=Q(status=DatasetStatus.REJECTED)),
            published=Count("id", filter=Q(status=DatasetStatus.PUBLISHED)),
        )
        serializer = self.serializer_class(summary)
        return success_response(data=serializer.data)


class DatasetBulkActionJobBaseView(StandardizedAPIView):
    permission_classes = [HasPermission]
    required_permissions = (
        "datasets.view_all_dataset",
        "datasets.review_dataset",
    )
    pagination_class = CustomPagination

    def paginate_queryset(self, queryset):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        return paginator, page

    def get_queryset(self):
        return DatasetBulkActionJob.objects.select_related("requested_by").order_by(
            "-created_at",
            "-id",
        )

    def get_filtered_queryset(self):
        queryset = self.get_queryset()
        status_value = self.request.query_params.get("status")
        if status_value:
            allowed_statuses = {
                choice for choice, _label in DatasetBulkActionJobStatus.CHOICES
            }
            if status_value not in allowed_statuses:
                raise ValidationError(
                    {
                        "status": [
                            f"Invalid status. Expected one of: {', '.join(sorted(allowed_statuses))}."
                        ]
                    }
                )
            queryset = queryset.filter(status=status_value)
        return queryset


class DatasetBulkActionJobListView(DatasetBulkActionJobBaseView):
    serializer_class = DatasetAdminBulkActionJobSerializer

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_admin_bulk_action_job_list",
        summary="List dataset bulk action jobs",
        description=(
            "Show queued and completed admin batch actions on existing datasets. "
            "Use this endpoint to poll job history, view completion state, and filter by status."
        ),
        parameters=[
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
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filter jobs by status.",
                enum=[choice for choice, _label in DatasetBulkActionJobStatus.CHOICES],
            ),
        ],
        responses={
            200: success_response_schema(
                "DatasetAdminBulkActionJobListSuccessResponse",
                DatasetAdminBulkActionJobListPayloadSerializer,
                description="Bulk action jobs returned successfully.",
            ),
            **standard_error_responses(
                "DatasetAdminBulkActionJobList",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        paginator, page = self.paginate_queryset(self.get_filtered_queryset())
        serializer = self.serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class DatasetBulkActionJobDetailView(DatasetBulkActionJobBaseView):
    serializer_class = DatasetAdminBulkActionJobDetailSerializer

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_admin_bulk_action_job_retrieve",
        summary="Get one dataset bulk action job",
        description=(
            "Return the full result for a batch action that was applied to existing datasets. "
            "This includes the datasets processed, failures, counts, timestamps, and any error message."
        ),
        responses={
            200: success_response_schema(
                "DatasetAdminBulkActionJobRetrieveSuccessResponse",
                DatasetAdminBulkActionJobDetailSerializer,
                description="Bulk action job returned successfully.",
            ),
            **standard_error_responses(
                "DatasetAdminBulkActionJobRetrieve",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, job_id):
        job = get_object_or_404(self.get_queryset(), pk=job_id)
        serializer = self.serializer_class(job)
        return success_response(data=serializer.data)


class DatasetBulkUploadJobBaseView(StandardizedAPIView):
    permission_classes = [HasPermission]
    required_permissions = (
        "datasets.view_all_dataset",
        "datasets.review_dataset",
    )
    pagination_class = CustomPagination

    def paginate_queryset(self, queryset):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        return paginator, page

    def get_queryset(self):
        return (
            DatasetBulkUploadJob.objects.select_related("requested_by")
            .prefetch_related("items__dataset", "items__dataset_version")
            .order_by("-created_at", "-id")
        )

    def get_filtered_queryset(self):
        queryset = self.get_queryset()
        status_value = self.request.query_params.get("status")
        if status_value:
            allowed_statuses = {
                choice for choice, _label in DatasetBulkUploadJobStatus.CHOICES
            }
            if status_value not in allowed_statuses:
                raise ValidationError(
                    {
                        "status": [
                            f"Invalid status. Expected one of: {', '.join(sorted(allowed_statuses))}."
                        ]
                    }
                )
            queryset = queryset.filter(status=status_value)
        return queryset


class DatasetBulkUploadJobListView(DatasetBulkUploadJobBaseView):
    serializer_class = DatasetBulkUploadJobSerializer

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_admin_bulk_upload_job_list",
        summary="List dataset bulk upload jobs",
        description=(
            "Show background jobs that uploaded many dataset files in one request. "
            "Use this endpoint to monitor upload progress and filter by job status."
        ),
        parameters=[
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
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filter jobs by status.",
                enum=[choice for choice, _label in DatasetBulkUploadJobStatus.CHOICES],
            ),
        ],
        responses={
            200: success_response_schema(
                "DatasetAdminBulkUploadJobListSuccessResponse",
                DatasetBulkUploadJobListPayloadSerializer,
                description="Bulk file upload jobs returned successfully.",
            ),
            **standard_error_responses(
                "DatasetAdminBulkUploadJobList",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        paginator, page = self.paginate_queryset(self.get_filtered_queryset())
        serializer = self.serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class DatasetBulkUploadJobDetailView(DatasetBulkUploadJobBaseView):
    serializer_class = DatasetBulkUploadJobDetailSerializer

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_admin_bulk_upload_job_retrieve",
        summary="Get one dataset bulk upload job",
        description=(
            "Return the full result for a bulk file upload request. "
            "This includes each uploaded file, the target dataset, per-item status, counts, timestamps, and errors."
        ),
        responses={
            200: success_response_schema(
                "DatasetAdminBulkUploadJobRetrieveSuccessResponse",
                DatasetBulkUploadJobDetailSerializer,
                description="Bulk file upload job returned successfully.",
            ),
            **standard_error_responses(
                "DatasetAdminBulkUploadJobRetrieve",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, job_id):
        job = get_object_or_404(self.get_queryset(), pk=job_id)
        serializer = self.serializer_class(job)
        return success_response(data=serializer.data)


class DatasetAdminBulkUploadView(StandardizedAPIView):
    permission_classes = [HasPermission]
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    serializer_class = DatasetBulkUploadJobCreateSerializer
    response_serializer_class = DatasetBulkUploadJobSerializer

    @property
    def required_permissions(self):
        permissions = [
            "datasets.view_all_dataset",
            "datasets.review_dataset",
        ]
        if self.request:
            try:
                publish_after_upload = parse_optional_bool(
                    self.request.data.get("publish_after_upload", False),
                    "publish_after_upload",
                )
            except ValidationError:
                publish_after_upload = False
            if publish_after_upload:
                permissions.append("datasets.publish_dataset")
        return tuple(permissions)

    def get_dataset_queryset(self):
        return Dataset.objects.select_related("category", "publisher_user")

    def _parse_items(self, request):
        raw_items = request.data.get("items")
        if isinstance(raw_items, str):
            try:
                items = json.loads(raw_items)
            except json.JSONDecodeError as exc:
                raise ValidationError({"items": ["Invalid JSON payload."]}) from exc
        else:
            items = raw_items
        if not isinstance(items, list):
            raise ValidationError({"items": ["Expected a list of upload items."]})
        return items

    def _build_upload_payload(self, request):
        payload = {
            "items": self._parse_items(request),
            "publish_after_upload": request.data.get("publish_after_upload", False),
            "reason": request.data.get("reason", ""),
        }
        serializer = self.serializer_class(data=payload)
        serializer.is_valid(raise_exception=True)
        files = request.FILES.getlist("files")
        if len(files) != len(serializer.validated_data["items"]):
            raise ValidationError(
                {
                    "files": [
                        "The number of files must match the number of upload items."
                    ]
                }
            )
        return serializer.validated_data, files

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_admin_bulk_upload",
        summary="Upload many dataset files in one request",
        description=(
            "Send multiple dataset files in a single multipart request. "
            "The API creates a background job, stores each file against its dataset, "
            "and Celery validates and processes the uploads asynchronously. "
            "Use a JSON 'items' field plus a matching repeated 'files' list. "
            "Each item must include dataset_id and may include dataset_version_id and is_primary."
        ),
        request={
            "multipart/form-data": OpenApiRequest(
                request=inline_serializer(
                    name="DatasetBulkUploadMultipartRequest",
                    fields={
                        "items": serializers.CharField(
                            help_text="JSON array of upload items.",
                        ),
                        "files": serializers.ListField(
                            child=serializers.FileField(),
                            required=True,
                            help_text="Repeated uploaded files.",
                        ),
                        "publish_after_upload": serializers.BooleanField(
                            required=False,
                            default=False,
                        ),
                        "reason": serializers.CharField(
                            required=False,
                            allow_blank=True,
                            max_length=500,
                        ),
                    },
                ),
                encoding={
                    "items": {"contentType": "application/json"},
                    "files": {"style": "form", "explode": True},
                },
            )
        },
        responses={
            202: success_response_schema(
                "DatasetAdminBulkUploadSuccessResponse",
                DatasetBulkUploadJobSerializer,
                description="Bulk file upload job queued successfully.",
            ),
            **standard_error_responses(
                "DatasetAdminBulkUpload",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def post(self, request):
        validated_data, files = self._build_upload_payload(request)
        items = validated_data["items"]

        with transaction.atomic():
            job = DatasetBulkUploadJob.objects.create(
                requested_by=request.user,
                publish_after_upload=validated_data.get("publish_after_upload", False),
                reason=validated_data.get("reason", ""),
                audit_context=request_audit_details(request),
                total_count=len(items),
            )

            for item_data, uploaded_file in zip(items, files):
                dataset = get_object_or_404(
                    self.get_dataset_queryset(), pk=item_data["dataset_id"]
                )
                dataset_version_id = item_data.get("dataset_version_id")
                dataset_version = None
                if dataset_version_id:
                    dataset_version = get_object_or_404(
                        DatasetVersion.objects.select_related("dataset"),
                        pk=dataset_version_id,
                    )
                    if dataset_version.dataset_id != dataset.id:
                        raise ValidationError(
                            {
                                "items": [
                                    "Each dataset_version_id must belong to the matching dataset_id."
                                ]
                            }
                        )

                DatasetBulkUploadJobItem.objects.create(
                    job=job,
                    dataset=dataset,
                    dataset_version=dataset_version,
                    uploaded_file=uploaded_file,
                    filename=uploaded_file.name,
                    is_primary=item_data.get("is_primary", True),
                )

        self.enqueue_bulk_upload_job(job)
        job.refresh_from_db()
        response_serializer = self.response_serializer_class(job)
        return success_response(
            data=response_serializer.data,
            message="Bulk dataset file upload job queued successfully.",
            status_code=status.HTTP_202_ACCEPTED,
        )

    def enqueue_bulk_upload_job(self, job):
        try:
            if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
                task_id = str(uuid.uuid4())
                DatasetBulkUploadJob.objects.filter(pk=job.pk).update(task_id=task_id)
                run_bulk_upload_job.run(str(job.id))
                return
            async_result = run_bulk_upload_job.delay(str(job.id))
            task_id = getattr(async_result, "id", "") or ""
            if task_id:
                DatasetBulkUploadJob.objects.filter(pk=job.pk).update(task_id=task_id)
        except Exception as exc:
            DatasetBulkUploadJob.objects.filter(pk=job.pk).update(
                status=DatasetBulkUploadJobStatus.FAILED,
                error=str(exc),
                completed_at=timezone.now(),
            )
            raise ValidationError(str(exc))


class DatasetAdminBulkActionView(DatasetBaseView):
    permission_classes = [HasPermission]
    serializer_class = DatasetAdminBulkActionSerializer
    response_serializer_class = DatasetAdminBulkActionJobSerializer

    @property
    def required_permissions(self):
        permissions = [
            "datasets.view_all_dataset",
            "datasets.review_dataset",
        ]
        if (
            self.request.data.get("action")
            == DatasetAdminBulkActionSerializer.ACTION_PUBLISH
        ):
            permissions.append("datasets.publish_dataset")
        return tuple(permissions)

    def get_dataset_queryset(self):
        return self.get_base_queryset()

    def enqueue_bulk_action_job(self, job):
        try:
            if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
                task_id = str(uuid.uuid4())
                DatasetBulkActionJob.objects.filter(pk=job.pk).update(task_id=task_id)
                run_bulk_action_job.run(str(job.id))
                return
            else:
                async_result = run_bulk_action_job.delay(str(job.id))
            task_id = getattr(async_result, "id", "") or ""
            if task_id:
                DatasetBulkActionJob.objects.filter(pk=job.pk).update(task_id=task_id)
        except Exception as exc:
            DatasetBulkActionJob.objects.filter(pk=job.pk).update(
                status=DatasetBulkActionJobStatus.FAILED,
                error=str(exc),
                completed_at=timezone.now(),
            )
            raise ValidationError(str(exc))

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_admin_bulk_action",
        summary="Change many existing datasets at once",
        description=(
            "Apply the same admin decision to many datasets in one request. "
            "This endpoint does not upload files; it approves, rejects, or publishes existing datasets "
            "and processes the changes in the background with Celery."
        ),
        request=DatasetAdminBulkActionSerializer,
        responses={
            202: success_response_schema(
                "DatasetAdminBulkActionSuccessResponse",
                DatasetAdminBulkActionJobSerializer,
                description="Bulk dataset action job queued successfully.",
            ),
            **standard_error_responses(
                "DatasetAdminBulkAction",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]
        dataset_ids = serializer.validated_data["dataset_ids"]
        reason = serializer.validated_data.get("reason", "")

        with transaction.atomic():
            job = DatasetBulkActionJob.objects.create(
                requested_by=request.user,
                action=action,
                dataset_ids=[str(dataset_id) for dataset_id in dataset_ids],
                reason=reason,
                audit_context=request_audit_details(request),
                requested_count=len(dataset_ids),
            )

        self.enqueue_bulk_action_job(job)
        job.refresh_from_db()
        response_serializer = self.response_serializer_class(job)
        return success_response(
            data=response_serializer.data,
            message="Bulk dataset action job queued successfully.",
            status_code=status.HTTP_202_ACCEPTED,
        )


class DatasetDetailView(DatasetBaseView):
    permission_classes = [CanAccessDataset]

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_retrieve",
        summary="Retrieve dataset",
        description="Return dataset details, metadata, tags, versions, and files for a visible dataset.",
        auth=[],
        parameters=[DATASET_ID_PARAMETER],
        responses={
            200: success_response_schema(
                "DatasetRetrieveSuccessResponse",
                DatasetDetailSerializer,
                description="Dataset returned successfully.",
            ),
            **standard_error_responses(
                "DatasetRetrieve",
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_id):
        return Response(
            self.serialize_detail(self.get_object()), status=status.HTTP_200_OK
        )

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_partial_update",
        summary="Partially update dataset",
        description="Update editable dataset fields. Owners can update drafts and rejected datasets. Dataset admins can update any dataset.",
        parameters=[DATASET_ID_PARAMETER],
        request=DatasetWriteSerializer,
        responses={
            200: success_response_schema(
                "DatasetPartialUpdateSuccessResponse",
                DatasetDetailSerializer,
                description="Dataset updated successfully.",
            ),
            **standard_error_responses(
                "DatasetPartialUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def patch(self, request, dataset_id):
        dataset = self.get_object()
        serializer = self.write_serializer_class(
            dataset, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        dataset = serializer.save()
        log_dataset_event(
            dataset,
            "dataset_updated",
            actor=request.user,
            details=request_audit_details(request, status=dataset.status),
        )
        return Response(self.serialize_detail(dataset), status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_destroy",
        summary="Soft delete dataset",
        description="Soft delete a dataset by setting `deleted_at`. Deleted datasets are hidden from discovery and related dataset endpoints.",
        parameters=[DATASET_ID_PARAMETER],
        responses={
            200: success_response_schema(
                "DatasetDestroySuccessResponse",
                description="Dataset soft deleted successfully.",
            ),
            **standard_error_responses(
                "DatasetDestroy",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def delete(self, request, dataset_id):
        dataset = self.get_object()
        log_dataset_event(
            dataset,
            "dataset_deleted",
            actor=request.user,
            details=request_audit_details(request, status=dataset.status),
        )
        dataset.delete()
        return success_response(message="Dataset deleted successfully.")


class DatasetBookmarkBaseView(StandardizedAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPagination

    def get_queryset(self):
        return (
            DatasetBookmark.objects.select_related(
                "user",
                "dataset",
                "dataset__publisher_user",
                "dataset__category",
            )
            .prefetch_related(
                "dataset__metadata",
                "dataset__dataset_tags__tag",
                "dataset__versions__files",
            )
            .filter(user=self.request.user)
            .order_by("-created_at", "-id")
        )

    def paginate_queryset(self, queryset):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        return paginator, page


class DatasetBookmarkListView(DatasetBookmarkBaseView):
    serializer_class = DatasetBookmarkSerializer

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_bookmark_list",
        summary="List saved datasets",
        description="Return the datasets saved by the authenticated user.",
        responses={
            200: success_response_schema(
                "DatasetBookmarkListSuccessResponse",
                DatasetBookmarkListPayloadSerializer,
                description="Saved datasets returned successfully.",
            ),
            **standard_error_responses(
                "DatasetBookmarkList",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        paginator, page = self.paginate_queryset(self.get_queryset())
        serializer = self.serializer_class(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


class DatasetBookmarkView(DatasetBaseView):
    permission_classes = [IsAuthenticated]
    serializer_class = DatasetBookmarkSerializer

    def get_base_queryset(self):
        return Dataset.objects.select_related(
            "publisher_user",
            "category",
        ).prefetch_related(
            "metadata",
            "dataset_tags__tag",
            "versions__files",
        ).filter(
            deleted_at__isnull=True,
        )

    def get_bookmark(self, dataset):
        return DatasetBookmark.objects.select_related(
            "dataset",
            "dataset__publisher_user",
            "dataset__category",
        ).prefetch_related(
            "dataset__metadata",
            "dataset__dataset_tags__tag",
            "dataset__versions__files",
        ).filter(user=self.request.user, dataset=dataset).first()

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_bookmark_save",
        summary="Save dataset",
        description="Save a dataset for the authenticated user.",
        parameters=[DATASET_ID_PARAMETER],
        responses={
            200: success_response_schema(
                "DatasetBookmarkSaveSuccessResponse",
                DatasetBookmarkSerializer,
                description="Dataset saved successfully.",
            ),
            201: success_response_schema(
                "DatasetBookmarkSaveCreatedResponse",
                DatasetBookmarkSerializer,
                description="Dataset saved successfully.",
            ),
            **standard_error_responses(
                "DatasetBookmarkSave",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, dataset_id):
        dataset = get_object_or_404(self.get_base_queryset(), pk=dataset_id)
        if not can_view_dataset(request.user, dataset):
            raise PermissionDenied("You cannot save this dataset.")

        bookmark, created = DatasetBookmark.objects.get_or_create(
            user=request.user,
            dataset=dataset,
        )
        bookmark = self.get_bookmark(bookmark.dataset) or bookmark
        serializer = self.serializer_class(bookmark, context={"request": request})
        return success_response(
            data=serializer.data,
            message="Dataset saved successfully.",
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_bookmark_remove",
        summary="Remove saved dataset",
        description="Remove a dataset from the authenticated user's saved list.",
        parameters=[DATASET_ID_PARAMETER],
        responses={
            200: success_response_schema(
                "DatasetBookmarkRemoveSuccessResponse",
                description="Dataset removed from saved list successfully.",
            ),
            **standard_error_responses(
                "DatasetBookmarkRemove",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def delete(self, request, dataset_id):
        dataset = get_object_or_404(self.get_base_queryset(), pk=dataset_id)
        bookmark = self.get_bookmark(dataset)
        if bookmark is None:
            return success_response(message="Dataset removed from saved list successfully.")

        bookmark.delete()
        return success_response(message="Dataset removed from saved list successfully.")


class DatasetSubmitReviewView(DatasetBaseView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_submit_review",
        summary="Submit dataset for review",
        description="Move a complete dataset from `draft` or `rejected` to `in_review` after metadata, tags, versions, and validated files are present.",
        parameters=[DATASET_ID_PARAMETER],
        request=DatasetSubmitReviewSerializer,
        responses={
            200: success_response_schema(
                "DatasetSubmitReviewSuccessResponse",
                DatasetDetailSerializer,
                description="Dataset submitted for review successfully.",
            ),
            **standard_error_responses(
                "DatasetSubmitReview",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, dataset_id):
        dataset = get_object_or_404(self.get_base_queryset(), pk=dataset_id)
        if not can_change_dataset(request.user, dataset):
            raise PermissionDenied(
                "You do not have permission to submit this dataset for review."
            )

        if dataset.status not in {DatasetStatus.DRAFT, DatasetStatus.REJECTED}:
            raise ValidationError(
                {
                    "status": [
                        "Only draft or rejected datasets can be submitted for review."
                    ]
                }
            )

        serializer = DatasetSubmitReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validate_dataset_ready_for_review(dataset)

        old_status = dataset.status
        dataset.status = DatasetStatus.IN_REVIEW
        dataset.visibility = False
        dataset.save(update_fields=["status", "visibility", "updated_at"])

        reason = serializer.validated_data.get("reason") or "Submitted for review."
        create_status_history(dataset, request.user, old_status, dataset.status, reason)
        log_dataset_event(
            dataset,
            "dataset_review_submitted",
            actor=request.user,
            details=request_audit_details(
                request,
                old_status=old_status,
                new_status=dataset.status,
                reason=reason,
            ),
        )
        return success_response(
            data=self.serialize_detail(dataset),
            message="Dataset submitted for review successfully.",
        )


class DatasetReviewView(DatasetBaseView):
    permission_classes = [CanReviewDataset]

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_review",
        summary="Approve or reject dataset review",
        description="Review a dataset currently in `in_review` status and transition it to `approved` or `rejected`.",
        parameters=[DATASET_ID_PARAMETER],
        request=DatasetReviewSerializer,
        responses={
            200: success_response_schema(
                "DatasetReviewSuccessResponse",
                DatasetDetailSerializer,
                description="Dataset review decision recorded successfully.",
            ),
            **standard_error_responses(
                "DatasetReview",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, dataset_id):
        dataset = self.get_object()
        serializer = DatasetReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if dataset.status != DatasetStatus.IN_REVIEW:
            raise ValidationError(
                {"status": ["Only datasets in review can be reviewed."]}
            )

        action_name = serializer.validated_data["action"]
        old_status = dataset.status
        if action_name == "approve":
            dataset.status = DatasetStatus.APPROVED
            reason = (
                serializer.validated_data.get("reason")
                or "Dataset approved for publication."
            )
            audit_action = "dataset_review_approved"
            success_message = "Dataset approved successfully."
        else:
            dataset.status = DatasetStatus.REJECTED
            dataset.visibility = False
            reason = serializer.validated_data["reason"]
            audit_action = "dataset_review_rejected"
            success_message = "Dataset rejected successfully."

        dataset.save(update_fields=["status", "visibility", "updated_at"])
        create_status_history(dataset, request.user, old_status, dataset.status, reason)
        log_dataset_event(
            dataset,
            audit_action,
            actor=request.user,
            details=request_audit_details(
                request,
                old_status=old_status,
                new_status=dataset.status,
                reason=reason,
            ),
        )
        return success_response(
            data=self.serialize_detail(dataset),
            message=success_message,
        )


class DatasetPublishView(DatasetBaseView):
    permission_classes = [CanPublishDataset]

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_publish",
        summary="Publish dataset",
        description="Publish an `approved` dataset, make it publicly visible, and set `published_at` if not already set.",
        parameters=[DATASET_ID_PARAMETER],
        request=DatasetPublishSerializer,
        responses={
            200: success_response_schema(
                "DatasetPublishSuccessResponse",
                DatasetDetailSerializer,
                description="Dataset published successfully.",
            ),
            **standard_error_responses(
                "DatasetPublish",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, dataset_id):
        dataset = self.get_object()
        serializer = DatasetPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if dataset.status != DatasetStatus.APPROVED:
            raise ValidationError(
                {"status": ["Only approved datasets can be published."]}
            )

        old_status = dataset.status
        dataset.status = DatasetStatus.PUBLISHED
        dataset.visibility = True
        dataset.published_at = dataset.published_at or timezone.now()
        dataset.save(
            update_fields=["status", "visibility", "published_at", "updated_at"]
        )

        reason = serializer.validated_data.get("reason") or "Published via API."
        create_status_history(dataset, request.user, old_status, dataset.status, reason)
        log_dataset_event(
            dataset,
            "dataset_published",
            actor=request.user,
            details=request_audit_details(
                request,
                old_status=old_status,
                new_status=dataset.status,
                reason=reason,
            ),
        )

        return success_response(
            data=self.serialize_detail(dataset),
            message="Dataset published successfully.",
        )


class DatasetUnpublishView(DatasetBaseView):
    permission_classes = [CanPublishDataset]

    @extend_schema(
        tags=["Dataset Workflow"],
        operation_id="dataset_unpublish",
        summary="Unpublish dataset",
        description=(
            "Unpublish a `published` dataset, remove it from public access, "
            "and return it to `approved` status."
        ),
        parameters=[DATASET_ID_PARAMETER],
        request=DatasetPublishSerializer,
        responses={
            200: success_response_schema(
                "DatasetUnpublishSuccessResponse",
                DatasetDetailSerializer,
                description="Dataset unpublished successfully.",
            ),
            **standard_error_responses(
                "DatasetUnpublish",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, dataset_id):
        dataset = self.get_object()
        serializer = DatasetPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if dataset.status != DatasetStatus.PUBLISHED:
            raise ValidationError(
                {"status": ["Only published datasets can be unpublished."]}
            )

        old_status = dataset.status
        dataset.status = DatasetStatus.APPROVED
        dataset.visibility = False
        dataset.save(update_fields=["status", "visibility", "updated_at"])

        reason = serializer.validated_data.get("reason") or "Unpublished via API."
        create_status_history(dataset, request.user, old_status, dataset.status, reason)
        log_dataset_event(
            dataset,
            "dataset_unpublished",
            actor=request.user,
            details=request_audit_details(
                request,
                old_status=old_status,
                new_status=dataset.status,
                reason=reason,
            ),
        )

        return success_response(
            data=self.serialize_detail(dataset),
            message="Dataset unpublished successfully.",
        )


class DatasetRestoreView(DatasetBaseView):
    permission_classes = [CanRestoreDataset]

    def get_restore_queryset(self):
        return Dataset.all_objects.select_related(
            "publisher_user",
            "category",
        ).prefetch_related(
            "metadata",
            "dataset_tags__tag",
            "versions__files",
        )

    def get_object(self):
        dataset = get_object_or_404(
            self.get_restore_queryset(), pk=self.kwargs["dataset_id"]
        )
        self.check_object_permissions(self.request, dataset)
        return dataset

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_restore",
        summary="Restore soft-deleted dataset",
        description=(
            "Restore a soft-deleted dataset by clearing `deleted_at`. "
            "The dataset returns with its previous status and visibility."
        ),
        parameters=[DATASET_ID_PARAMETER],
        request=DatasetRestoreSerializer,
        responses={
            200: success_response_schema(
                "DatasetRestoreSuccessResponse",
                DatasetDetailSerializer,
                description="Dataset restored successfully.",
            ),
            **standard_error_responses(
                "DatasetRestore",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, dataset_id):
        dataset = self.get_object()
        serializer = DatasetRestoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not dataset.is_deleted:
            raise ValidationError(
                {"dataset": ["Only deleted datasets can be restored."]}
            )

        dataset.restore()

        reason = serializer.validated_data.get("reason") or "Dataset restored via API."
        log_dataset_event(
            dataset,
            "dataset_restored",
            actor=request.user,
            details=request_audit_details(
                request,
                status=dataset.status,
                reason=reason,
            ),
        )

        return success_response(
            data=self.serialize_detail(dataset),
            message="Dataset restored successfully.",
        )


class DatasetTransferOwnerView(DatasetBaseView):
    permission_classes = [HasPermission]
    required_permissions = (
        "datasets.view_all_dataset",
        "datasets.change_dataset",
    )

    @extend_schema(
        tags=["Datasets"],
        operation_id="dataset_transfer_owner",
        summary="Transfer dataset owner",
        description=(
            "Transfer dataset ownership to another active user who can manage datasets. "
            "This also resynchronizes dataset metadata publisher names."
        ),
        parameters=[DATASET_ID_PARAMETER],
        request=DatasetTransferOwnerSerializer,
        responses={
            200: success_response_schema(
                "DatasetTransferOwnerSuccessResponse",
                DatasetDetailSerializer,
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, dataset_id):
        dataset = self.get_object()
        serializer = DatasetTransferOwnerSerializer(
            data=request.data,
            context={"dataset": dataset},
        )
        serializer.is_valid(raise_exception=True)

        new_owner = serializer.validated_data["new_owner"]
        old_owner = dataset.publisher_user
        reason = (
            serializer.validated_data.get("reason")
            or "Dataset owner transferred via API."
        )

        with transaction.atomic():
            dataset.publisher_user = new_owner
            dataset.save(update_fields=["publisher_user", "updated_at"])

            for metadata in dataset.metadata.all():
                metadata.save(update_fields=["publisher_name", "updated_at"])

        log_dataset_event(
            dataset,
            "dataset_owner_transferred",
            actor=request.user,
            details=request_audit_details(
                request,
                status=dataset.status,
                reason=reason,
                old_owner_id=str(old_owner.id),
                old_owner_email=old_owner.email,
                new_owner_id=str(new_owner.id),
                new_owner_email=new_owner.email,
            ),
        )

        return success_response(
            data=self.serialize_detail(dataset),
            message="Dataset owner transferred successfully.",
        )


class DatasetScopedViewSet(StandardizedModelViewSet):
    permission_classes = [CanAccessDatasetRelatedObject]
    dataset_lookup = "dataset"
    immutable_parent_fields = ()
    create_audit_action = None
    update_audit_action = None
    destroy_audit_action = None

    def get_queryset(self):
        return filter_related_queryset_by_dataset_access(
            self.base_queryset(),
            self.request.user,
            self.dataset_lookup,
        )

    def base_queryset(self):
        raise NotImplementedError

    def get_create_dataset(self, serializer):
        raise NotImplementedError

    def get_create_save_kwargs(self):
        return {}

    def validate_immutable_parent_fields(self, data):
        errors = {
            field: ["This field cannot be updated."]
            for field in self.immutable_parent_fields
            if field in data
        }
        if errors:
            raise ValidationError(errors)

    def audit_details(self, instance, **extra):
        return request_audit_details(self.request, **extra)

    def perform_create(self, serializer):
        dataset = self.get_create_dataset(serializer)
        if not can_change_dataset(self.request.user, dataset):
            raise PermissionDenied("You do not have permission to modify this dataset.")
        serializer.save(**self.get_create_save_kwargs())
        instance = serializer.instance
        if self.create_audit_action:
            log_dataset_event(
                dataset,
                self.create_audit_action,
                actor=self.request.user,
                target=instance,
                details=self.audit_details(instance),
            )

    def perform_update(self, serializer):
        instance = serializer.save()
        if self.update_audit_action:
            log_dataset_event(
                get_dataset_from_object(instance),
                self.update_audit_action,
                actor=self.request.user,
                target=instance,
                details=self.audit_details(instance),
            )

    def perform_destroy(self, instance):
        dataset = get_dataset_from_object(instance)
        if self.destroy_audit_action:
            log_dataset_event(
                dataset,
                self.destroy_audit_action,
                actor=self.request.user,
                target=instance,
                details=self.audit_details(instance),
            )
        super().perform_destroy(instance)

    def update(self, request, *args, **kwargs):
        self.validate_immutable_parent_fields(request.data)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self.validate_immutable_parent_fields(request.data)
        return super().partial_update(request, *args, **kwargs)


class DatasetReadOnlyScopedViewSet(StandardizedReadOnlyModelViewSet):
    dataset_lookup = "dataset"

    def get_queryset(self):
        return filter_related_queryset_by_dataset_access(
            self.base_queryset(),
            self.request.user,
            self.dataset_lookup,
        )

    def base_queryset(self):
        raise NotImplementedError


@extend_schema_view(
    list=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_version_list",
        summary="List dataset versions",
        description="List versions for visible datasets.",
        auth=[],
        responses={
            200: success_response_schema(
                "DatasetVersionListSuccessResponse",
                DatasetVersionSerializer(many=True),
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_version_retrieve",
        summary="Retrieve dataset version",
        description="Return a single dataset version.",
        auth=[],
        responses={
            200: success_response_schema(
                "DatasetVersionRetrieveSuccessResponse",
                DatasetVersionSerializer,
            ),
            **standard_error_responses(
                "DatasetVersionRetrieve",
                include_404=True,
            ),
        },
    ),
    create=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_version_create",
        summary="Create dataset version",
        description="Create a new version for an editable dataset.",
        request=DatasetVersionSerializer,
        responses={
            201: success_response_schema(
                "DatasetVersionCreateSuccessResponse",
                DatasetVersionSerializer,
            ),
            **standard_error_responses(
                "DatasetVersionCreate",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    ),
    update=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_version_update",
        summary="Replace dataset version",
        description="Replace a dataset version record.",
        request=DatasetVersionSerializer,
        responses={
            200: success_response_schema(
                "DatasetVersionUpdateSuccessResponse",
                DatasetVersionSerializer,
            ),
            **standard_error_responses(
                "DatasetVersionUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    partial_update=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_version_partial_update",
        summary="Partially update dataset version",
        description="Update selected fields on a dataset version.",
        request=DatasetVersionSerializer,
        responses={
            200: success_response_schema(
                "DatasetVersionPartialUpdateSuccessResponse",
                DatasetVersionSerializer,
            ),
            **standard_error_responses(
                "DatasetVersionPartialUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    destroy=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_version_destroy",
        summary="Delete dataset version",
        description="Delete a dataset version from an editable dataset.",
        responses={
            200: success_response_schema(
                "DatasetVersionDestroySuccessResponse",
                description="Dataset version deleted successfully.",
            ),
            **standard_error_responses(
                "DatasetVersionDestroy",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
)
class DatasetVersionView(DatasetScopedViewSet):
    serializer_class = DatasetVersionSerializer
    dataset_lookup = "dataset"
    immutable_parent_fields = ("dataset_id",)
    create_audit_action = "version_created"
    update_audit_action = "version_updated"
    destroy_audit_action = "version_deleted"

    def base_queryset(self):
        return DatasetVersion.objects.select_related(
            "dataset",
            "dataset__publisher_user",
            "dataset__category",
            "created_by",
        )

    def get_create_dataset(self, serializer):
        return serializer.validated_data["dataset"]

    def get_create_save_kwargs(self):
        return {"created_by": self.request.user}


@extend_schema_view(
    list=extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_list",
        summary="List dataset files",
        description="List files for visible datasets.",
        auth=[],
        responses={
            200: success_response_schema(
                "DatasetFileListSuccessResponse",
                DatasetFileSerializer(many=True),
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_retrieve",
        summary="Retrieve dataset file metadata",
        description="Return file metadata for a single dataset file.",
        auth=[],
        responses={
            200: success_response_schema(
                "DatasetFileRetrieveSuccessResponse",
                DatasetFileSerializer,
            ),
            **standard_error_responses(
                "DatasetFileRetrieve",
                include_404=True,
            ),
        },
    ),
    create=extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_create",
        summary="Upload dataset file",
        description=DATASET_FILE_UPLOAD_DESCRIPTION,
        request=DATASET_FILE_CREATE_REQUEST,
        responses={
            201: success_response_schema(
                "DatasetFileCreateSuccessResponse",
                DatasetFileSerializer,
            ),
            **standard_error_responses(
                "DatasetFileCreate",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    ),
    update=extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_update",
        summary="Replace dataset file metadata or binary",
        description=DATASET_FILE_UPLOAD_DESCRIPTION,
        request=DATASET_FILE_UPDATE_REQUEST,
        responses={
            200: success_response_schema(
                "DatasetFileUpdateSuccessResponse",
                DatasetFileSerializer,
            ),
            **standard_error_responses(
                "DatasetFileUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    partial_update=extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_partial_update",
        summary="Partially update dataset file metadata or binary",
        description=DATASET_FILE_UPLOAD_DESCRIPTION,
        request=DATASET_FILE_UPDATE_REQUEST,
        responses={
            200: success_response_schema(
                "DatasetFilePartialUpdateSuccessResponse",
                DatasetFileSerializer,
            ),
            **standard_error_responses(
                "DatasetFilePartialUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    destroy=extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_destroy",
        summary="Delete dataset file",
        description="Delete a file from an editable dataset.",
        responses={
            200: success_response_schema(
                "DatasetFileDestroySuccessResponse",
                description="Dataset file deleted successfully.",
            ),
            **standard_error_responses(
                "DatasetFileDestroy",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
)
class DatasetFileView(DatasetScopedViewSet):
    serializer_class = DatasetFileSerializer
    dataset_lookup = "dataset_version__dataset"
    immutable_parent_fields = ("dataset_version_id", "dataset_id")
    create_audit_action = "file_uploaded"
    update_audit_action = "file_updated"
    destroy_audit_action = "file_deleted"
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_permissions(self):
        if self.action == "validate_file":
            self.required_permissions = (
                "datasets.view_all_dataset",
                "datasets.review_dataset",
            )
            return [HasPermission()]
        return super().get_permissions()

    def base_queryset(self):
        return DatasetFile.objects.select_related(
            "dataset_version",
            "dataset_version__dataset",
            "dataset_version__dataset__publisher_user",
            "dataset_version__dataset__category",
            "uploaded_by",
        )

    def get_create_dataset(self, serializer):
        dataset_version = serializer.validated_data.get("dataset_version")
        if dataset_version is not None:
            return dataset_version.dataset
        return serializer.validated_data["dataset_id"]

    def get_create_save_kwargs(self):
        return {"uploaded_by": self.request.user}

    @extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_validate",
        summary="Validate dataset file",
        description=(
            "Re-run validation for a dataset file. "
            "Only dataset administrators can access this endpoint."
        ),
        request=DatasetFileValidateSerializer,
        responses={
            200: success_response_schema(
                "DatasetFileValidateSuccessResponse",
                DatasetFileSerializer,
                description="Dataset file validation completed successfully.",
            ),
            **standard_error_responses(
                "DatasetFileValidate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="validate",
        permission_classes=[HasPermission],
    )
    def validate_file(self, request, pk=None):
        dataset_file = self.get_object()
        serializer = DatasetFileValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        inspection = inspect_dataset_file(
            dataset_file.file,
            original_name=dataset_file.filename,
            file_size=dataset_file.file_size,
        )
        is_valid = not inspection["errors"]
        admin_note = serializer.validated_data.get("validation_notes", "").strip()

        if is_valid:
            validation_notes = admin_note or "Manual validation passed."
        else:
            validation_notes = "; ".join(inspection["errors"])
            if admin_note:
                validation_notes = f"{validation_notes} Admin note: {admin_note}"

        dataset_file.filename = inspection["filename"] or dataset_file.filename
        if inspection["file_size"] is not None:
            dataset_file.file_size = inspection["file_size"]
        dataset_file.file_format = inspection["file_format"]
        if inspection["checksum"]:
            dataset_file.checksum = inspection["checksum"]
        dataset_file.validation_status = (
            FileValidationStatus.VALIDATED
            if is_valid
            else FileValidationStatus.REJECTED
        )
        dataset_file.validated_at = timezone.now()
        dataset_file.validation_notes = validation_notes
        dataset_file.is_safe = is_valid
        dataset_file.save(
            update_fields=[
                "filename",
                "file_size",
                "file_format",
                "checksum",
                "validation_status",
                "validated_at",
                "validation_notes",
                "is_safe",
                "updated_at",
            ]
        )

        log_dataset_event(
            dataset_file.dataset_version.dataset,
            "file_validated" if is_valid else "file_validation_rejected",
            actor=request.user,
            target=dataset_file,
            details=request_audit_details(
                request,
                filename=dataset_file.filename,
                validation_status=dataset_file.validation_status,
                validation_notes=dataset_file.validation_notes,
                is_safe=dataset_file.is_safe,
            ),
        )

        return success_response(
            data=self.get_serializer(dataset_file).data,
            message=(
                "Dataset file validated successfully."
                if is_valid
                else "Dataset file validation completed with rejection."
            ),
        )

    @extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_download",
        summary="Download dataset file",
        description="Download the dataset file binary. Public access is allowed for published datasets.",
        auth=[],
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="Binary file download.",
            ),
            **standard_error_responses(
                "DatasetFileDownload",
                include_404=True,
            ),
        },
    )
    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        dataset_file = self.get_object()
        log_dataset_event(
            dataset_file.dataset_version.dataset,
            "file_downloaded",
            actor=request.user if request.user.is_authenticated else None,
            target=dataset_file,
            details=request_audit_details(request, filename=dataset_file.filename),
        )
        return FileResponse(
            dataset_file.file.open("rb"),
            as_attachment=True,
            filename=dataset_file.filename,
        )

    @extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_data",
        summary="Read structured dataset content",
        description=(
            "Return parsed rows for structured dataset files. "
            "Supported formats are csv, tsv, json, xls, xlsx, sdmx/xml, and pdf. "
            "Public access is allowed for published datasets; authenticated owners and dataset admins can also access private datasets."
        ),
        auth=[],
        parameters=[
            OpenApiParameter(
                name="offset",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Zero-based row offset into the parsed dataset rows.",
                default=0,
            ),
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Maximum number of rows to return. Minimum 1, maximum 200.",
                default=50,
            ),
        ],
        responses={
            200: success_response_schema(
                "DatasetFileDataSuccessResponse",
                DatasetFileDataResponseSerializer,
                description="Structured dataset rows returned successfully.",
            ),
            **standard_error_responses(
                "DatasetFileData",
                include_400=True,
                include_404=True,
            ),
        },
    )
    @action(detail=True, methods=["get"], url_path="data")
    def data(self, request, pk=None):
        dataset_file = self.get_object()
        params = DatasetFileDataQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        if (
            dataset_file.validation_status != FileValidationStatus.VALIDATED
            or not dataset_file.is_safe
        ):
            raise ValidationError(
                {
                    "file": [
                        "Structured API access is available only for validated safe files."
                    ]
                }
            )

        payload = {
            "file_id": dataset_file.id,
            "filename": dataset_file.filename,
            "file_format": dataset_file.file_format,
            **build_structured_payload(
                dataset_file,
                offset=params.validated_data["offset"],
                limit=params.validated_data["limit"],
            ),
        }

        log_dataset_event(
            dataset_file.dataset_version.dataset,
            "file_data_accessed",
            actor=request.user if request.user.is_authenticated else None,
            target=dataset_file,
            details=request_audit_details(
                request,
                filename=dataset_file.filename,
                offset=payload["offset"],
                limit=payload["limit"],
                returned_rows=payload["returned_rows"],
            ),
        )
        return success_response(
            data=payload,
            message="Structured dataset content retrieved successfully.",
        )

    @extend_schema(
        tags=["Dataset Files"],
        operation_id="dataset_file_chart",
        summary="Build chart-ready dataset content",
        description=(
            "Return chart-ready data for structured dataset files. "
            "Supported formats are csv, tsv, json, xls, xlsx, and sdmx/xml. "
            "PDF documents are not supported for chart generation. "
            "Public access is allowed for published datasets; authenticated owners and dataset admins can also access private datasets."
        ),
        auth=[],
        parameters=[
            OpenApiParameter(
                name="chart_type",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=["bar", "pie", "line", "scatter"],
                default="bar",
                description="Chart type to generate.",
            ),
            OpenApiParameter(
                name="x_field",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Field to use on the x axis or for grouping.",
            ),
            OpenApiParameter(
                name="y_field",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Field to use for numeric aggregation or scatter y values.",
            ),
            OpenApiParameter(
                name="group_by",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Optional grouping field for bar, pie, and line charts.",
            ),
            OpenApiParameter(
                name="metric",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=["count", "sum", "avg", "min", "max"],
                default="count",
                description="Aggregation metric for grouped charts.",
            ),
            OpenApiParameter(
                name="sort",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=["asc", "desc"],
                description="Sort order for chart points.",
            ),
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Maximum number of chart points to return.",
                default=20,
            ),
        ],
        responses={
            200: success_response_schema(
                "DatasetFileChartSuccessResponse",
                DatasetFileChartResponseSerializer,
                description="Chart-ready dataset content returned successfully.",
            ),
            **standard_error_responses(
                "DatasetFileChart",
                include_400=True,
                include_404=True,
            ),
        },
    )
    @action(detail=True, methods=["get"], url_path="chart")
    def chart(self, request, pk=None):
        dataset_file = self.get_object()
        params = DatasetFileChartQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        if (
            dataset_file.validation_status != FileValidationStatus.VALIDATED
            or not dataset_file.is_safe
        ):
            raise ValidationError(
                {"file": ["Chart API access is available only for validated safe files."]}
            )

        structured_payload = build_structured_payload(dataset_file, offset=0, limit=None)
        payload = {
            "file_id": dataset_file.id,
            "filename": dataset_file.filename,
            "file_format": dataset_file.file_format,
            **build_dataset_chart_payload(
                dataset_file,
                structured_payload,
                chart_type=params.validated_data["chart_type"],
                x_field=params.validated_data.get("x_field"),
                y_field=params.validated_data.get("y_field"),
                group_by=params.validated_data.get("group_by"),
                metric=params.validated_data["metric"],
                sort=params.validated_data.get("sort"),
                limit=params.validated_data["limit"],
            ),
        }

        log_dataset_event(
            dataset_file.dataset_version.dataset,
            "file_chart_accessed",
            actor=request.user if request.user.is_authenticated else None,
            target=dataset_file,
            details=request_audit_details(
                request,
                filename=dataset_file.filename,
                chart_type=payload["chart_type"],
                x_field=payload.get("x_field"),
                y_field=payload.get("y_field"),
                group_by=payload.get("group_by"),
                metric=payload.get("metric"),
                point_count=payload["point_count"],
            ),
        )
        return success_response(
            data=payload,
            message="Chart-ready dataset content retrieved successfully.",
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_tag_link_list",
        summary="List dataset tag links",
        description="List dataset-to-tag relationships for visible datasets.",
        auth=[],
        responses={
            200: success_response_schema(
                "DatasetTagLinkListSuccessResponse",
                DatasetTagSerializer(many=True),
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_tag_link_retrieve",
        summary="Retrieve dataset tag link",
        description="Return a single dataset-to-tag relationship.",
        auth=[],
        responses={
            200: success_response_schema(
                "DatasetTagLinkRetrieveSuccessResponse",
                DatasetTagSerializer,
            ),
            **standard_error_responses(
                "DatasetTagLinkRetrieve",
                include_404=True,
            ),
        },
    ),
    create=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_tag_link_create",
        summary="Attach tag to dataset",
        description="Link a taxonomy tag to an editable dataset.",
        request=DatasetTagSerializer,
        responses={
            201: success_response_schema(
                "DatasetTagLinkCreateSuccessResponse",
                DatasetTagSerializer,
            ),
            **standard_error_responses(
                "DatasetTagLinkCreate",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    ),
    update=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_tag_link_update",
        summary="Replace dataset tag link",
        description="Update a dataset tag relationship.",
        request=DatasetTagSerializer,
        responses={
            200: success_response_schema(
                "DatasetTagLinkUpdateSuccessResponse",
                DatasetTagSerializer,
            ),
            **standard_error_responses(
                "DatasetTagLinkUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    partial_update=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_tag_link_partial_update",
        summary="Partially update dataset tag link",
        description="Update selected fields on a dataset tag relationship.",
        request=DatasetTagSerializer,
        responses={
            200: success_response_schema(
                "DatasetTagLinkPartialUpdateSuccessResponse",
                DatasetTagSerializer,
            ),
            **standard_error_responses(
                "DatasetTagLinkPartialUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    destroy=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_tag_link_destroy",
        summary="Remove tag from dataset",
        description="Delete a dataset tag relationship from an editable dataset.",
        responses={
            200: success_response_schema(
                "DatasetTagLinkDestroySuccessResponse",
                description="Dataset tag link deleted successfully.",
            ),
            **standard_error_responses(
                "DatasetTagLinkDestroy",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
)
class DatasetTagView(DatasetScopedViewSet):
    serializer_class = DatasetTagSerializer
    dataset_lookup = "dataset"
    immutable_parent_fields = ("dataset_id",)
    create_audit_action = "tag_linked"
    update_audit_action = "tag_updated"
    destroy_audit_action = "tag_unlinked"

    def base_queryset(self):
        return DatasetTag.objects.select_related(
            "dataset",
            "dataset__publisher_user",
            "dataset__category",
            "tag",
        )

    def get_create_dataset(self, serializer):
        return serializer.validated_data["dataset"]


@extend_schema_view(
    list=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_metadata_list",
        summary="List dataset metadata records",
        description="List metadata records for visible datasets.",
        auth=[],
        responses={
            200: success_response_schema(
                "DatasetMetadataListSuccessResponse",
                DatasetMetadataSerializer(many=True),
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_metadata_retrieve",
        summary="Retrieve dataset metadata record",
        description="Return a single dataset metadata record.",
        auth=[],
        responses={
            200: success_response_schema(
                "DatasetMetadataRetrieveSuccessResponse",
                DatasetMetadataSerializer,
            ),
            **standard_error_responses(
                "DatasetMetadataRetrieve",
                include_404=True,
            ),
        },
    ),
    create=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_metadata_create",
        summary="Create dataset metadata",
        description="Create metadata for an editable dataset. Each dataset supports one metadata record.",
        request=DatasetMetadataSerializer,
        responses={
            201: success_response_schema(
                "DatasetMetadataCreateSuccessResponse",
                DatasetMetadataSerializer,
            ),
            **standard_error_responses(
                "DatasetMetadataCreate",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    ),
    update=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_metadata_update",
        summary="Replace dataset metadata",
        description="Replace the metadata record for an editable dataset.",
        request=DatasetMetadataSerializer,
        responses={
            200: success_response_schema(
                "DatasetMetadataUpdateSuccessResponse",
                DatasetMetadataSerializer,
            ),
            **standard_error_responses(
                "DatasetMetadataUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    partial_update=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_metadata_partial_update",
        summary="Partially update dataset metadata",
        description="Update selected metadata fields for an editable dataset.",
        request=DatasetMetadataSerializer,
        responses={
            200: success_response_schema(
                "DatasetMetadataPartialUpdateSuccessResponse",
                DatasetMetadataSerializer,
            ),
            **standard_error_responses(
                "DatasetMetadataPartialUpdate",
                include_400=True,
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
    destroy=extend_schema(
        tags=["Datasets"],
        operation_id="dataset_metadata_destroy",
        summary="Delete dataset metadata",
        description="Delete the metadata record from an editable dataset.",
        responses={
            200: success_response_schema(
                "DatasetMetadataDestroySuccessResponse",
                description="Dataset metadata deleted successfully.",
            ),
            **standard_error_responses(
                "DatasetMetadataDestroy",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
)
class DatasetMetadataView(DatasetScopedViewSet):
    serializer_class = DatasetMetadataSerializer
    dataset_lookup = "dataset"
    immutable_parent_fields = ("dataset_id",)
    create_audit_action = "metadata_created"
    update_audit_action = "metadata_updated"
    destroy_audit_action = "metadata_deleted"

    def base_queryset(self):
        return DatasetMetadata.objects.select_related(
            "dataset",
            "dataset__publisher_user",
            "dataset__category",
        )

    def get_create_dataset(self, serializer):
        return serializer.validated_data["dataset"]


@extend_schema_view(
    list=extend_schema(
        tags=["Dataset Audit"],
        operation_id="dataset_status_history_list",
        summary="List dataset status history",
        description="List workflow status transitions for datasets visible to the authenticated user.",
        responses={
            200: success_response_schema(
                "DatasetStatusHistoryListSuccessResponse",
                DatasetStatusHistorySerializer(many=True),
            ),
            **standard_error_responses(
                "DatasetStatusHistoryList",
                include_401=True,
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Dataset Audit"],
        operation_id="dataset_status_history_retrieve",
        summary="Retrieve dataset status history record",
        description="Return a single dataset status history record.",
        responses={
            200: success_response_schema(
                "DatasetStatusHistoryRetrieveSuccessResponse",
                DatasetStatusHistorySerializer,
            ),
            **standard_error_responses(
                "DatasetStatusHistoryRetrieve",
                include_401=True,
                include_404=True,
            ),
        },
    ),
)
class DatasetStatusHistoryView(DatasetReadOnlyScopedViewSet):
    serializer_class = DatasetStatusHistorySerializer
    dataset_lookup = "dataset"

    def base_queryset(self):
        return DatasetStatusHistory.objects.select_related(
            "dataset",
            "dataset__publisher_user",
            "dataset__category",
            "changed_by",
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Dataset Audit"],
        operation_id="dataset_indexing_status_list",
        summary="List dataset indexing statuses",
        description="List indexing status records for datasets visible to the authenticated user.",
        responses={
            200: success_response_schema(
                "DatasetIndexingStatusListSuccessResponse",
                IndexingStatusSerializer(many=True),
            ),
            **standard_error_responses(
                "DatasetIndexingStatusList",
                include_401=True,
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Dataset Audit"],
        operation_id="dataset_indexing_status_retrieve",
        summary="Retrieve dataset indexing status",
        description="Return a single dataset indexing status record.",
        responses={
            200: success_response_schema(
                "DatasetIndexingStatusRetrieveSuccessResponse",
                IndexingStatusSerializer,
            ),
            **standard_error_responses(
                "DatasetIndexingStatusRetrieve",
                include_401=True,
                include_404=True,
            ),
        },
    ),
)
class IndexingStatusView(DatasetReadOnlyScopedViewSet):
    serializer_class = IndexingStatusSerializer
    dataset_lookup = "dataset"

    def base_queryset(self):
        return IndexingStatus.objects.select_related(
            "dataset",
            "dataset__publisher_user",
            "dataset__category",
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Dataset Audit"],
        operation_id="dataset_audit_log_list",
        summary="List dataset audit logs",
        description="List audit events. Dataset owners see their own logs. Dataset admins see all logs.",
        responses={
            200: success_response_schema(
                "DatasetAuditLogListSuccessResponse",
                DatasetAuditLogSerializer(many=True),
            ),
            **standard_error_responses(
                "DatasetAuditLogList",
                include_401=True,
            ),
        },
    ),
    retrieve=extend_schema(
        tags=["Dataset Audit"],
        operation_id="dataset_audit_log_retrieve",
        summary="Retrieve dataset audit log",
        description="Return a single dataset audit event visible to the authenticated user.",
        responses={
            200: success_response_schema(
                "DatasetAuditLogRetrieveSuccessResponse",
                DatasetAuditLogSerializer,
            ),
            **standard_error_responses(
                "DatasetAuditLogRetrieve",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    ),
)
class DatasetAuditLogView(DatasetReadOnlyScopedViewSet):
    serializer_class = DatasetAuditLogSerializer
    permission_classes = [CanViewDatasetAuditLog]
    dataset_lookup = "dataset"

    def get_queryset(self):
        user = self.request.user
        queryset = self.base_queryset().filter(dataset__deleted_at__isnull=True)
        if not user or not user.is_authenticated:
            return queryset.none()
        if has_dataset_admin_access(user):
            return queryset
        return queryset.filter(dataset__publisher_user=user)

    def base_queryset(self):
        return DatasetAuditLog.objects.select_related(
            "dataset",
            "dataset__publisher_user",
            "dataset__category",
            "actor",
        )
