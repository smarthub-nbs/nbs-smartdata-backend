from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
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
    DatasetFile,
    DatasetMetadata,
    DatasetStatus,
    DatasetStatusHistory,
    DatasetTag,
    DatasetVersion,
    FileValidationStatus,
    IndexingStatus,
    Tag,
)
from djapps.datasets.helpers import (
    create_status_history,
    filter_related_queryset_by_dataset_access,
    request_audit_details,
    validate_dataset_ready_for_review,
)
from djapps.datasets.permissions import (
    CanAccessDataset,
    CanAccessDatasetRelatedObject,
    CanCreateDataset,
    CanPublishDataset,
    CanReviewDataset,
    CanViewDatasetAuditLog,
    can_change_dataset,
    get_dataset_from_object,
    has_dataset_admin_access,
)
from djapps.datasets.serializers import (
    CategorySerializer,
    DatasetAuditLogSerializer,
    DatasetDetailSerializer,
    DatasetFileSerializer,
    DatasetFileDataQuerySerializer,
    DatasetFileDataResponseSerializer,
    DatasetMetadataSerializer,
    DatasetPublishSerializer,
    DatasetReviewSerializer,
    DatasetSerializer,
    DatasetStatusHistorySerializer,
    DatasetSubmitReviewSerializer,
    DatasetTagSerializer,
    DatasetVersionSerializer,
    DatasetWriteSerializer,
    IndexingStatusSerializer,
    TagSerializer,
)
from djapps.datasets.openapi import (
    DATASET_FILE_UPLOAD_DESCRIPTION,
    DATASET_FILE_UPLOAD_REQUEST,
    DATASET_ID_PARAMETER,
    DATASET_LIST_PARAMETERS,
)
from djapps.datasets.structured_data import build_structured_payload
from djapps.user_management.api.permissions import IsAdminOrSuperuser
from utils.query import build_identifier_filter


class PublicReadAdminWriteViewSet(StandardizedModelViewSet):
    permission_classes = (IsAdminOrSuperuser,)

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        return [IsAdminOrSuperuser()]


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


class DatasetBaseView(StandardizedAPIView):
    serializer_class = DatasetSerializer
    detail_serializer_class = DatasetDetailSerializer
    write_serializer_class = DatasetWriteSerializer

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
        dataset = get_object_or_404(self.get_base_queryset(), pk=self.kwargs["dataset_id"])
        self.check_object_permissions(self.request, dataset)
        return dataset

    def serialize_detail(self, dataset):
        return self.detail_serializer_class(dataset).data


class DatasetView(DatasetBaseView):

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [CanCreateDataset()]

    def get_queryset(self):
        queryset = self.get_base_queryset()
        user = self.request.user
        params = self.request.query_params

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

        search = params.get("q")
        if search:
            queryset = queryset.filter(
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

        category = params.get("category")
        if category:
            queryset = queryset.filter(
                build_identifier_filter("category__id", "category__slug__iexact", category)
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

        if params.get("status") and has_dataset_admin_access(user):
            queryset = queryset.filter(status=params["status"])

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
        return Response(self.serialize_detail(self.get_object()), status=status.HTTP_200_OK)

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
        serializer = self.write_serializer_class(dataset, data=request.data, partial=True)
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
            raise PermissionDenied("You do not have permission to submit this dataset for review.")

        if dataset.status not in {DatasetStatus.DRAFT, DatasetStatus.REJECTED}:
            raise ValidationError(
                {"status": ["Only draft or rejected datasets can be submitted for review."]}
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
            raise ValidationError({"status": ["Only datasets in review can be reviewed."]})

        action_name = serializer.validated_data["action"]
        old_status = dataset.status
        if action_name == "approve":
            dataset.status = DatasetStatus.APPROVED
            reason = serializer.validated_data.get("reason") or "Dataset approved for publication."
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
        dataset.save(update_fields=["status", "visibility", "published_at", "updated_at"])

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
        request=DATASET_FILE_UPLOAD_REQUEST,
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
        request=DATASET_FILE_UPLOAD_REQUEST,
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
        request=DATASET_FILE_UPLOAD_REQUEST,
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
    parser_classes = (MultiPartParser, FormParser)

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
                {"file": ["Structured API access is available only for validated safe files."]}
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
