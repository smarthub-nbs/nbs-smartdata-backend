import time

from django.db import connection
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response

from config.api.responses import StandardizedAPIView, success_response
from config.api.schema import success_response_schema, standard_error_responses
from djapps.datasets.audit import log_dataset_event
from djapps.datasets.helpers import request_audit_details
from djapps.datasets.models import (
    Category,
    Dataset,
    DatasetFile,
    DatasetMetadata,
    DatasetStatus,
    DatasetVersion,
    FileValidationStatus,
    Tag,
)
from djapps.datasets.structured_data import build_structured_payload
from djapps.datasets.serializers import (
    CategorySerializer,
    DatasetFileDataQuerySerializer,
    DatasetFileDataResponseSerializer,
    DatasetMetadataSummarySerializer,
)
from djapps.user_management.api.permissions import HasAnyGroup
from utils.pagination import CustomPagination
from utils.query import build_identifier_filter

from .authentication import APIKeyAuthentication
from .constants import FREQUENCY_LABELS, SCHEMA_SAMPLE_LIMIT
from .helpers import annotate_dataset_last_changed, build_preview_payload, build_schema_payload
from .models import APIKey, APIUsageLog
from .openapi import (
    API_KEY_HEADER_PARAMETER,
    DEVELOPER_API_KEY_LIST_PAYLOAD,
    DEVELOPER_API_USAGE_LIST_PAYLOAD,
    GATEWAY_DATASET_CHANGE_LIST_PAYLOAD,
    GATEWAY_DATASET_LIST_PARAMETERS,
    GATEWAY_DATASET_LIST_PAYLOAD,
    GATEWAY_DATASET_LOOKUP_PARAMETER,
    GATEWAY_FILE_ID_PARAMETER,
    GATEWAY_VERSION_ID_PARAMETER,
)
from .permission import HasAPIKey
from .serializers import (
    APIKeyActionResponseSerializer,
    APIKeyDetailSerializer,
    APIKeyRequestSerializer,
    APIUsageLogSerializer,
    DatasetFilePreviewQuerySerializer,
    DatasetFilePreviewResponseSerializer,
    DatasetFileSchemaResponseSerializer,
    DatasetFormatSerializer,
    GatewayDatasetChangeSerializer,
    GatewayDatasetFacetsSerializer,
    GatewayDatasetStatsSerializer,
    GatewayFacetValueSerializer,
    GatewayFrequencySummarySerializer,
    GatewayTagSummarySerializer,
    IssuedAPIKeySerializer,
    OpenDatasetFileListSerializer,
    OpenDatasetSerializer,
    OpenDatasetVersionSerializer,
    STRUCTURED_DATA_SUPPORTED_FORMATS,
)
from .services import (
    get_or_create_developer_consumer,
    issue_api_key,
    regenerate_api_key,
    revoke_api_key,
)


class OpenDatasetBaseAPIView(StandardizedAPIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasAPIKey]
    serializer_class = OpenDatasetSerializer
    pagination_class = CustomPagination

    def initial(self, request, *args, **kwargs):
        self._started_at = time.monotonic()
        self._usage_logged = False
        self._usage_dataset = None
        super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        self.log_usage(request, response)
        return response

    def get_base_dataset_queryset(self):
        return Dataset.objects.select_related(
            "category",
            "publisher_user",
        ).prefetch_related(
            "metadata",
            "dataset_tags__tag",
            "versions__files",
        ).filter(
            visibility=True,
            status=DatasetStatus.PUBLISHED,
        )

    def get_updated_since(self):
        if hasattr(self, "_updated_since_value"):
            return self._updated_since_value

        raw_value = self.request.query_params.get("updated_since")
        if not raw_value:
            self._updated_since_value = None
            return None

        parsed = parse_datetime(raw_value)
        if parsed is None:
            raise serializers.ValidationError(
                {"updated_since": ["Use a valid ISO 8601 datetime."]}
            )
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())

        self._updated_since_value = parsed
        return parsed

    def build_dataset_queryset(self, *, include_activity=False):
        queryset = self.get_base_dataset_queryset()
        params = self.request.query_params
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
                versions__files__file_format__iexact=file_format.lower(),
                versions__files__validation_status=FileValidationStatus.VALIDATED,
                versions__files__is_safe=True,
            )

        updated_since = self.get_updated_since()
        if include_activity or updated_since is not None:
            queryset = annotate_dataset_last_changed(queryset)
        if updated_since is not None:
            queryset = queryset.filter(last_changed_at__gte=updated_since)

        return queryset.order_by("-published_at", "-created_at").distinct()

    def get_queryset(self):
        return self.build_dataset_queryset()

    def get_activity_queryset(self):
        return self.build_dataset_queryset(include_activity=True).order_by(
            "-last_changed_at",
            "-published_at",
            "-created_at",
        )

    def get_object(self):
        dataset_lookup = self.kwargs["dataset_lookup"]
        dataset = get_object_or_404(
            self.get_queryset(),
            build_identifier_filter("id", "slug__iexact", dataset_lookup),
        )
        self._usage_dataset = dataset
        return dataset

    def get_serializer_context(self):
        return {"request": self.request}

    def get_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", self.get_serializer_context())
        return self.serializer_class(*args, **kwargs)

    def get_public_file_queryset(self):
        return DatasetFile.objects.select_related(
            "dataset_version",
            "dataset_version__dataset",
        ).filter(
            deleted_at__isnull=True,
            dataset_version__deleted_at__isnull=True,
            dataset_version__dataset__visibility=True,
            dataset_version__dataset__status=DatasetStatus.PUBLISHED,
            dataset_version__dataset__deleted_at__isnull=True,
            validation_status=FileValidationStatus.VALIDATED,
            is_safe=True,
        )

    def get_public_version_queryset(self):
        return DatasetVersion.objects.select_related("dataset").prefetch_related("files").filter(
            deleted_at__isnull=True,
            dataset__visibility=True,
            dataset__status=DatasetStatus.PUBLISHED,
            dataset__deleted_at__isnull=True,
        )

    def get_latest_dataset_version(self, dataset):
        version = self.get_public_version_queryset().filter(dataset=dataset).order_by("-created_at").first()
        if version is None:
            raise Http404
        return version

    def get_preferred_dataset_file(self, dataset=None, version=None):
        queryset = self.get_public_file_queryset()
        if version is not None:
            queryset = queryset.filter(dataset_version=version)
        elif dataset is not None:
            queryset = queryset.filter(dataset_version__dataset=dataset)
        dataset_file = queryset.order_by("-dataset_version__created_at", "-is_primary", "filename").first()
        if dataset_file is None:
            raise Http404
        return dataset_file

    def paginate_queryset(self, queryset):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        return paginator, page

    def get_dataset_filter_ids(self):
        return self.build_dataset_queryset().values_list("id", flat=True)

    def get_category_facets(self):
        dataset_ids = self.get_dataset_filter_ids()
        return Category.objects.filter(
            deleted_at__isnull=True,
            dataset__id__in=dataset_ids,
            dataset__deleted_at__isnull=True,
        ).annotate(
            dataset_count=Count(
                "dataset",
                filter=Q(dataset__id__in=dataset_ids, dataset__deleted_at__isnull=True),
                distinct=True,
            )
        ).order_by("name", "slug")

    def get_tag_facets(self):
        dataset_ids = self.get_dataset_filter_ids()
        return Tag.objects.filter(
            deleted_at__isnull=True,
            tag_datasets__dataset__id__in=dataset_ids,
            tag_datasets__deleted_at__isnull=True,
        ).annotate(
            dataset_count=Count(
                "tag_datasets__dataset",
                filter=Q(
                    tag_datasets__dataset__id__in=dataset_ids,
                    tag_datasets__deleted_at__isnull=True,
                ),
                distinct=True,
            )
        ).order_by("name", "slug")

    def get_license_facets(self):
        dataset_ids = self.get_dataset_filter_ids()
        return list(
            DatasetMetadata.objects.filter(
                deleted_at__isnull=True,
                dataset__id__in=dataset_ids,
            )
            .exclude(license__isnull=True)
            .exclude(license="")
            .values("license")
            .annotate(dataset_count=Count("dataset", distinct=True))
            .order_by("license")
        )

    def get_publisher_facets(self):
        dataset_ids = self.get_dataset_filter_ids()
        return list(
            DatasetMetadata.objects.filter(
                deleted_at__isnull=True,
                dataset__id__in=dataset_ids,
            )
            .exclude(publisher_name__isnull=True)
            .exclude(publisher_name="")
            .values("publisher_name")
            .annotate(dataset_count=Count("dataset", distinct=True))
            .order_by("publisher_name")
        )

    def get_frequency_facets(self):
        dataset_ids = self.get_dataset_filter_ids()
        rows = (
            DatasetMetadata.objects.filter(
                deleted_at__isnull=True,
                dataset__id__in=dataset_ids,
            )
            .exclude(frequency="")
            .values("frequency")
            .annotate(dataset_count=Count("dataset", distinct=True))
        )
        order_map = {value: index for index, value in enumerate(FREQUENCY_LABELS.keys())}
        return sorted(
            [
                {
                    "value": item["frequency"],
                    "label": FREQUENCY_LABELS.get(item["frequency"], item["frequency"]),
                    "dataset_count": item["dataset_count"],
                }
                for item in rows
            ],
            key=lambda item: order_map.get(item["value"], len(order_map)),
        )

    def get_region_facets(self):
        dataset_ids = self.get_dataset_filter_ids()
        return list(
            DatasetMetadata.objects.filter(
                deleted_at__isnull=True,
                dataset__id__in=dataset_ids,
            )
            .exclude(region="")
            .values("region")
            .annotate(dataset_count=Count("dataset", distinct=True))
            .order_by("region")
        )

    def get_year_facets(self):
        dataset_ids = self.get_dataset_filter_ids()
        return list(
            DatasetMetadata.objects.filter(
                deleted_at__isnull=True,
                dataset__id__in=dataset_ids,
            )
            .exclude(year__isnull=True)
            .values("year")
            .annotate(dataset_count=Count("dataset", distinct=True))
            .order_by("-year")
        )

    def get_format_facets(self):
        dataset_ids = self.get_dataset_filter_ids()
        return [
            {
                **item,
                "structured_data_supported": item["file_format"].lower() in STRUCTURED_DATA_SUPPORTED_FORMATS,
            }
            for item in DatasetFile.objects.filter(
                deleted_at__isnull=True,
                dataset_version__deleted_at__isnull=True,
                dataset_version__dataset__id__in=dataset_ids,
                validation_status=FileValidationStatus.VALIDATED,
                is_safe=True,
            )
            .exclude(file_format__isnull=True)
            .exclude(file_format="")
            .values("file_format")
            .annotate(
                dataset_count=Count("dataset_version__dataset", distinct=True),
                file_count=Count("id"),
            )
            .order_by("file_format")
        ]

    def get_client_ip(self, request):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    def log_usage(self, request, response):
        if self._usage_logged or not hasattr(response, "status_code"):
            return

        if APIUsageLog._meta.db_table not in connection.introspection.table_names():
            self._usage_logged = True
            return

        data = getattr(response, "data", None)
        error_code = None
        if isinstance(data, dict):
            error_code = data.get("error", {}).get("code")

        started_at = getattr(self, "_started_at", None)
        if started_at is None:
            response_time_ms = None
        else:
            response_time_ms = max(int((time.monotonic() - started_at) * 1000), 0)

        try:
            APIUsageLog.objects.create(
                api_key=getattr(request, "api_key", None),
                consumer=getattr(request, "api_consumer", None),
                endpoint=request.path,
                method=request.method,
                status_code=response.status_code,
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                dataset_id=getattr(self._usage_dataset, "id", None),
                response_time_ms=response_time_ms,
                error_code=error_code,
            )
        except Exception:
            pass

        self._usage_logged = True


class OpenDatasetListAPIView(OpenDatasetBaseAPIView):
    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_list",
        summary="List open datasets",
        description=(
            "Return published public datasets for open use. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, *GATEWAY_DATASET_LIST_PARAMETERS],
        responses={
            200: success_response_schema(
                "GatewayDatasetListSuccessResponse",
                GATEWAY_DATASET_LIST_PAYLOAD,
                description="Open datasets returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetList",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        queryset = self.get_queryset()
        paginator, page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class OpenDatasetDetailAPIView(OpenDatasetBaseAPIView):
    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_retrieve",
        summary="Retrieve open dataset",
        description=(
            "Return a published public dataset by UUID or slug. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, GATEWAY_DATASET_LOOKUP_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetRetrieveSuccessResponse",
                OpenDatasetSerializer,
                description="Open dataset returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetRetrieve",
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_lookup):
        serializer = self.get_serializer(self.get_object())
        return Response(serializer.data)


class OpenDatasetMetadataAPIView(OpenDatasetBaseAPIView):
    serializer_class = DatasetMetadataSummarySerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_metadata",
        summary="Retrieve open dataset metadata",
        description=(
            "Return metadata records for a published public dataset. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, GATEWAY_DATASET_LOOKUP_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetMetadataSuccessResponse",
                DatasetMetadataSummarySerializer(many=True),
                description="Open dataset metadata returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetMetadata",
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_lookup):
        dataset = self.get_object()
        serializer = self.serializer_class(dataset.metadata.order_by("-created_at"), many=True)
        return Response(serializer.data)


class OpenDatasetVersionListAPIView(OpenDatasetBaseAPIView):
    serializer_class = OpenDatasetVersionSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_version_list",
        summary="List public dataset versions",
        description=(
            "Return public versions for a published public dataset. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, GATEWAY_DATASET_LOOKUP_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetVersionListSuccessResponse",
                OpenDatasetVersionSerializer(many=True),
                description="Public dataset versions returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetVersionList",
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_lookup):
        dataset = self.get_object()
        versions = self.get_public_version_queryset().filter(dataset=dataset).order_by("-created_at")
        serializer = self.serializer_class(versions, many=True, context=self.get_serializer_context())
        return Response(serializer.data)


class OpenDatasetVersionDetailAPIView(OpenDatasetBaseAPIView):
    serializer_class = OpenDatasetVersionSerializer

    def get_version_object(self, dataset):
        return get_object_or_404(
            self.get_public_version_queryset().filter(dataset=dataset),
            pk=self.kwargs["version_id"],
        )

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_version_retrieve",
        summary="Retrieve public dataset version",
        description=(
            "Return a single public version for a published public dataset. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[
            API_KEY_HEADER_PARAMETER,
            GATEWAY_DATASET_LOOKUP_PARAMETER,
            GATEWAY_VERSION_ID_PARAMETER,
        ],
        responses={
            200: success_response_schema(
                "GatewayDatasetVersionRetrieveSuccessResponse",
                OpenDatasetVersionSerializer,
                description="Public dataset version returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetVersionRetrieve",
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_lookup, version_id):
        dataset = self.get_object()
        serializer = self.serializer_class(
            self.get_version_object(dataset),
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)


class OpenDatasetLatestVersionAPIView(OpenDatasetBaseAPIView):
    serializer_class = OpenDatasetVersionSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_latest_version",
        summary="Retrieve latest public dataset version",
        description=(
            "Return the latest public version for a published public dataset. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, GATEWAY_DATASET_LOOKUP_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetLatestVersionSuccessResponse",
                OpenDatasetVersionSerializer,
                description="Latest dataset version returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetLatestVersion",
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_lookup):
        dataset = self.get_object()
        serializer = self.serializer_class(
            self.get_latest_dataset_version(dataset),
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)


class OpenDatasetFileListAPIView(OpenDatasetBaseAPIView):
    serializer_class = OpenDatasetFileListSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_file_list",
        summary="List public dataset files",
        description=(
            "Return validated safe files belonging to a published public dataset. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, GATEWAY_DATASET_LOOKUP_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetFileListSuccessResponse",
                OpenDatasetFileListSerializer(many=True),
                description="Public dataset files returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetFileList",
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_lookup):
        dataset = self.get_object()
        files = self.get_public_file_queryset().filter(
            dataset_version__dataset=dataset,
        ).order_by("-dataset_version__created_at", "-is_primary", "filename")
        serializer = self.serializer_class(files, many=True, context=self.get_serializer_context())
        return Response(serializer.data)


class OpenDatasetDownloadAPIView(OpenDatasetBaseAPIView):
    def get_download_file(self):
        dataset = self.get_object()
        return self.get_preferred_dataset_file(dataset=dataset)

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_download",
        summary="Download public dataset primary file",
        description=(
            "Download the latest validated safe file for a published public dataset, "
            "preferring the primary file when available. A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, GATEWAY_DATASET_LOOKUP_PARAMETER],
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="Binary file download.",
            ),
            **standard_error_responses(
                "GatewayDatasetDownload",
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_lookup):
        dataset_file = self.get_download_file()
        log_dataset_event(
            dataset_file.dataset_version.dataset,
            "file_downloaded",
            actor=request.user if getattr(request.user, "is_authenticated", False) else None,
            target=dataset_file,
            details=request_audit_details(
                request,
                filename=dataset_file.filename,
                source="gateway",
                resolved_from="dataset_download",
            ),
        )
        return FileResponse(
            dataset_file.file.open("rb"),
            as_attachment=True,
            filename=dataset_file.filename,
        )


class OpenDatasetLatestDataAPIView(OpenDatasetBaseAPIView):
    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_latest_data",
        summary="Read latest public dataset structured content",
        description=(
            "Return parsed structured content from the preferred file on the latest public dataset version. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[
            API_KEY_HEADER_PARAMETER,
            GATEWAY_DATASET_LOOKUP_PARAMETER,
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
                "GatewayDatasetLatestDataSuccessResponse",
                DatasetFileDataResponseSerializer,
                description="Latest structured dataset content returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetLatestData",
                include_400=True,
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_lookup):
        dataset = self.get_object()
        version = self.get_latest_dataset_version(dataset)
        dataset_file = self.get_preferred_dataset_file(version=version)

        params = DatasetFileDataQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

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
            dataset,
            "file_data_accessed",
            actor=request.user if getattr(request.user, "is_authenticated", False) else None,
            target=dataset_file,
            details=request_audit_details(
                request,
                filename=dataset_file.filename,
                source="gateway",
                resolved_from="latest_version",
                offset=payload["offset"],
                limit=payload["limit"],
                returned_rows=payload["returned_rows"],
            ),
        )
        return success_response(
            data=payload,
            message="Latest structured dataset content retrieved successfully.",
        )


class OpenCategoryListAPIView(OpenDatasetBaseAPIView):
    serializer_class = CategorySerializer

    def get_queryset(self):
        return Category.objects.filter(
            dataset__visibility=True,
            dataset__status=DatasetStatus.PUBLISHED,
            dataset__deleted_at__isnull=True,
        ).order_by("name").distinct()

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_category_list",
        summary="List public dataset categories",
        description=(
            "Return categories that have at least one published public dataset. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayCategoryListSuccessResponse",
                CategorySerializer(many=True),
                description="Public dataset categories returned successfully.",
            ),
            **standard_error_responses(
                "GatewayCategoryList",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        serializer = self.serializer_class(self.get_queryset(), many=True)
        return Response(serializer.data)


class OpenTagListAPIView(OpenDatasetBaseAPIView):
    serializer_class = GatewayTagSummarySerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_tag_list",
        summary="List public dataset tags",
        description=(
            "Return tags used by at least one published public dataset. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayTagListSuccessResponse",
                GatewayTagSummarySerializer(many=True),
                description="Public dataset tags returned successfully.",
            ),
            **standard_error_responses(
                "GatewayTagList",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        serializer = self.serializer_class(self.get_tag_facets(), many=True)
        return Response(serializer.data)


class OpenDatasetLicenseListAPIView(OpenDatasetBaseAPIView):
    serializer_class = GatewayFacetValueSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_license_list",
        summary="List public dataset licenses",
        description=(
            "Return distinct license values used by published public datasets. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetLicenseListSuccessResponse",
                GatewayFacetValueSerializer(many=True),
                description="Public dataset licenses returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetLicenseList",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        payload = [
            {"value": item["license"], "dataset_count": item["dataset_count"]}
            for item in self.get_license_facets()
        ]
        serializer = self.serializer_class(payload, many=True)
        return Response(serializer.data)


class OpenDatasetPublisherListAPIView(OpenDatasetBaseAPIView):
    serializer_class = GatewayFacetValueSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_publisher_list",
        summary="List public dataset publishers",
        description=(
            "Return distinct publisher names used by published public datasets. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetPublisherListSuccessResponse",
                GatewayFacetValueSerializer(many=True),
                description="Public dataset publishers returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetPublisherList",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        payload = [
            {"value": item["publisher_name"], "dataset_count": item["dataset_count"]}
            for item in self.get_publisher_facets()
        ]
        serializer = self.serializer_class(payload, many=True)
        return Response(serializer.data)


class OpenDatasetFrequencyListAPIView(OpenDatasetBaseAPIView):
    serializer_class = GatewayFrequencySummarySerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_frequency_list",
        summary="List public dataset frequencies",
        description=(
            "Return distinct update frequencies used by published public datasets. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetFrequencyListSuccessResponse",
                GatewayFrequencySummarySerializer(many=True),
                description="Public dataset frequencies returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetFrequencyList",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        serializer = self.serializer_class(self.get_frequency_facets(), many=True)
        return Response(serializer.data)


class OpenDatasetRegionListAPIView(OpenDatasetBaseAPIView):
    serializer_class = GatewayFacetValueSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_region_list",
        summary="List public dataset regions",
        description=(
            "Return distinct regions used by published public datasets. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetRegionListSuccessResponse",
                GatewayFacetValueSerializer(many=True),
                description="Public dataset regions returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetRegionList",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        payload = [
            {"value": item["region"], "dataset_count": item["dataset_count"]}
            for item in self.get_region_facets()
        ]
        serializer = self.serializer_class(payload, many=True)
        return Response(serializer.data)


class OpenDatasetFacetsAPIView(OpenDatasetBaseAPIView):
    serializer_class = GatewayDatasetFacetsSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_facets",
        summary="List public dataset facets",
        description=(
            "Return aggregated facet counts for the current public dataset filter set. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, *GATEWAY_DATASET_LIST_PARAMETERS],
        responses={
            200: success_response_schema(
                "GatewayDatasetFacetsSuccessResponse",
                GatewayDatasetFacetsSerializer,
                description="Public dataset facets returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetFacets",
                include_400=True,
                include_401=True,
            ),
        },
    )
    def get(self, request):
        payload = {
            "total_datasets": self.get_queryset().count(),
            "categories": list(self.get_category_facets().values("id", "name", "slug", "dataset_count")),
            "tags": list(self.get_tag_facets().values("id", "name", "slug", "dataset_count")),
            "licenses": [
                {"value": item["license"], "dataset_count": item["dataset_count"]}
                for item in self.get_license_facets()
            ],
            "publishers": [
                {"value": item["publisher_name"], "dataset_count": item["dataset_count"]}
                for item in self.get_publisher_facets()
            ],
            "frequencies": self.get_frequency_facets(),
            "regions": [
                {"value": item["region"], "dataset_count": item["dataset_count"]}
                for item in self.get_region_facets()
            ],
            "years": [
                {"value": item["year"], "dataset_count": item["dataset_count"]}
                for item in self.get_year_facets()
            ],
            "formats": self.get_format_facets(),
        }
        serializer = self.serializer_class(payload)
        return Response(serializer.data)


class OpenDatasetChangeListAPIView(OpenDatasetBaseAPIView):
    serializer_class = GatewayDatasetChangeSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_change_list",
        summary="List public dataset changes",
        description=(
            "Return published public datasets ordered by latest detected change time. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, *GATEWAY_DATASET_LIST_PARAMETERS],
        responses={
            200: success_response_schema(
                "GatewayDatasetChangeListSuccessResponse",
                GATEWAY_DATASET_CHANGE_LIST_PAYLOAD,
                description="Public dataset changes returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetChangeList",
                include_400=True,
                include_401=True,
            ),
        },
    )
    def get(self, request):
        queryset = self.get_activity_queryset()
        paginator, page = self.paginate_queryset(queryset)
        serializer = self.serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class OpenDatasetFormatListAPIView(OpenDatasetBaseAPIView):
    serializer_class = DatasetFormatSerializer

    def get_queryset(self):
        return self.get_format_facets()

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_format_list",
        summary="List public dataset formats",
        description=(
            "Return distinct validated safe file formats available across published public datasets. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetFormatListSuccessResponse",
                DatasetFormatSerializer(many=True),
                description="Public dataset formats returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetFormatList",
                include_401=True,
            ),
        },
    )
    def get(self, request):
        serializer = self.serializer_class(self.get_queryset(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OpenDatasetStatsAPIView(OpenDatasetBaseAPIView):
    serializer_class = GatewayDatasetStatsSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_stats",
        summary="Retrieve public dataset stats",
        description=(
            "Return aggregate public statistics for a published public dataset. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, GATEWAY_DATASET_LOOKUP_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetStatsSuccessResponse",
                GatewayDatasetStatsSerializer,
                description="Public dataset stats returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetStats",
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, dataset_lookup):
        dataset = get_object_or_404(
            self.get_activity_queryset(),
            build_identifier_filter("id", "slug__iexact", dataset_lookup),
        )
        self._usage_dataset = dataset
        versions = list(
            self.get_public_version_queryset().filter(dataset=dataset).order_by("-created_at")
        )
        files = list(
            self.get_public_file_queryset().filter(dataset_version__dataset=dataset).order_by(
                "-dataset_version__created_at",
                "-is_primary",
                "filename",
            )
        )
        latest_version = versions[0] if versions else None
        latest_file = files[0] if files else None
        payload = {
            "dataset_id": dataset.id,
            "slug": dataset.slug,
            "category": dataset.category,
            "published_at": dataset.published_at,
            "last_changed_at": dataset.last_changed_at,
            "metadata_record_count": dataset.metadata.count(),
            "tag_count": dataset.dataset_tags.count(),
            "version_count": len(versions),
            "downloadable_file_count": len(files),
            "structured_file_count": sum(
                1 for file in files if (file.file_format or "").lower() in STRUCTURED_DATA_SUPPORTED_FORMATS
            ),
            "file_formats": sorted({file.file_format.lower() for file in files if file.file_format}),
            "latest_version_id": latest_version.id if latest_version is not None else None,
            "latest_version_number": latest_version.version_number if latest_version is not None else None,
            "latest_version_created_at": latest_version.created_at if latest_version is not None else None,
            "latest_file_id": latest_file.id if latest_file is not None else None,
            "latest_filename": latest_file.filename if latest_file is not None else None,
            "latest_file_format": latest_file.file_format if latest_file is not None else None,
        }
        serializer = self.serializer_class(payload)
        return Response(serializer.data)


class OpenDatasetFileResourceAPIView(OpenDatasetBaseAPIView):
    def get_object(self):
        dataset_file = get_object_or_404(
            self.get_public_file_queryset(),
            pk=self.kwargs["file_id"],
        )
        self._usage_dataset = dataset_file.dataset_version.dataset
        return dataset_file


class OpenDatasetFileSchemaAPIView(OpenDatasetFileResourceAPIView):
    serializer_class = DatasetFileSchemaResponseSerializer

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_file_schema",
        summary="Read public dataset file schema",
        description=(
            "Return inferred schema information for a validated safe public dataset file. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, GATEWAY_FILE_ID_PARAMETER],
        responses={
            200: success_response_schema(
                "GatewayDatasetFileSchemaSuccessResponse",
                DatasetFileSchemaResponseSerializer,
                description="Public dataset file schema returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetFileSchema",
                include_400=True,
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, file_id):
        dataset_file = self.get_object()
        structured_payload = build_structured_payload(dataset_file, offset=0, limit=SCHEMA_SAMPLE_LIMIT)
        payload = build_schema_payload(dataset_file, structured_payload)

        log_dataset_event(
            dataset_file.dataset_version.dataset,
            "file_schema_accessed",
            actor=request.user if getattr(request.user, "is_authenticated", False) else None,
            target=dataset_file,
            details=request_audit_details(
                request,
                filename=dataset_file.filename,
                source="gateway",
            ),
        )
        serializer = self.serializer_class(payload)
        return Response(serializer.data)


class OpenDatasetFilePreviewAPIView(OpenDatasetFileResourceAPIView):
    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_file_preview",
        summary="Preview public dataset file content",
        description=(
            "Return a small preview of structured content for a validated safe public dataset file. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[
            API_KEY_HEADER_PARAMETER,
            GATEWAY_FILE_ID_PARAMETER,
            OpenApiParameter(
                name="offset",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Zero-based preview offset.",
                default=0,
            ),
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Maximum preview size. Minimum 1, maximum 20.",
                default=5,
            ),
        ],
        responses={
            200: success_response_schema(
                "GatewayDatasetFilePreviewSuccessResponse",
                DatasetFilePreviewResponseSerializer,
                description="Public dataset file preview returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetFilePreview",
                include_400=True,
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, file_id):
        dataset_file = self.get_object()
        params = DatasetFilePreviewQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        structured_payload = build_structured_payload(
            dataset_file,
            offset=params.validated_data["offset"],
            limit=params.validated_data["limit"],
        )
        payload = build_preview_payload(dataset_file, structured_payload)

        log_dataset_event(
            dataset_file.dataset_version.dataset,
            "file_previewed",
            actor=request.user if getattr(request.user, "is_authenticated", False) else None,
            target=dataset_file,
            details=request_audit_details(
                request,
                filename=dataset_file.filename,
                source="gateway",
                offset=payload["offset"],
                limit=payload["limit"],
                returned_rows=payload["returned_rows"],
            ),
        )
        return success_response(
            data=payload,
            message="Dataset file preview retrieved successfully.",
        )


class OpenDatasetFileDownloadAPIView(OpenDatasetFileResourceAPIView):

    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_file_download",
        summary="Download public dataset file",
        description=(
            "Download a validated safe file from a published public dataset. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[API_KEY_HEADER_PARAMETER, GATEWAY_FILE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="Binary file download.",
            ),
            **standard_error_responses(
                "GatewayDatasetFileDownload",
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, file_id):
        dataset_file = self.get_object()
        log_dataset_event(
            dataset_file.dataset_version.dataset,
            "file_downloaded",
            actor=request.user if getattr(request.user, "is_authenticated", False) else None,
            target=dataset_file,
            details=request_audit_details(request, filename=dataset_file.filename, source="gateway"),
        )
        return FileResponse(
            dataset_file.file.open("rb"),
            as_attachment=True,
            filename=dataset_file.filename,
        )


class OpenDatasetFileDataAPIView(OpenDatasetFileResourceAPIView):
    @extend_schema(
        tags=["Gateway"],
        operation_id="gateway_dataset_file_data",
        summary="Read structured public dataset content",
        description=(
            "Return parsed rows for a validated safe public dataset file. "
            "Supported formats are csv, tsv, json, xls, xlsx, sdmx/xml, and pdf. "
            "A valid `X-API-Key` header is required."
        ),
        auth=[],
        parameters=[
            API_KEY_HEADER_PARAMETER,
            GATEWAY_FILE_ID_PARAMETER,
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
                "GatewayDatasetFileDataSuccessResponse",
                DatasetFileDataResponseSerializer,
                description="Structured dataset rows returned successfully.",
            ),
            **standard_error_responses(
                "GatewayDatasetFileData",
                include_400=True,
                include_401=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, file_id):
        dataset_file = self.get_object()
        params = DatasetFileDataQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

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
            actor=request.user if getattr(request.user, "is_authenticated", False) else None,
            target=dataset_file,
            details=request_audit_details(
                request,
                filename=dataset_file.filename,
                source="gateway",
                offset=payload["offset"],
                limit=payload["limit"],
                returned_rows=payload["returned_rows"],
            ),
        )
        return success_response(
            data=payload,
            message="Structured dataset content retrieved successfully.",
        )


class DeveloperAPIBaseView(StandardizedAPIView):
    permission_classes = [HasAnyGroup]
    required_groups = ("developer", "admin")
    pagination_class = CustomPagination

    def get_api_key_queryset(self):
        return APIKey.objects.select_related("consumer").prefetch_related("scopes").filter(
            consumer__user=self.request.user
        ).order_by("-created_at")

    def get_api_key_object(self):
        return get_object_or_404(self.get_api_key_queryset(), pk=self.kwargs["id"])

    def get_usage_queryset(self):
        return APIUsageLog.objects.select_related("api_key", "consumer").filter(
            Q(api_key__consumer__user=self.request.user)
            | Q(consumer__user=self.request.user)
        ).order_by("-created_at", "-id")

    def paginate_queryset(self, queryset):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        return paginator, page


class DeveloperAPIKeyRequestAPIView(DeveloperAPIBaseView):
    serializer_class = APIKeyRequestSerializer

    @extend_schema(
        tags=["Developer API Keys"],
        operation_id="developer_api_key_request",
        summary="Request API key",
        description="Create a developer API key for the authenticated developer account.",
        request=APIKeyRequestSerializer,
        responses={
            201: success_response_schema(
                "DeveloperAPIKeyRequestSuccessResponse",
                IssuedAPIKeySerializer,
                description="API key created successfully.",
            ),
            **standard_error_responses(
                "DeveloperAPIKeyRequest",
                include_400=True,
                include_401=True,
                include_403=True,
            ),
        },
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        consumer = get_or_create_developer_consumer(
            request.user,
            consumer_name=serializer.validated_data.get("consumer_name"),
            organization_name=serializer.validated_data.get("organization_name"),
        )
        api_key, raw_key = issue_api_key(
            consumer=consumer,
            name=serializer.validated_data["name"],
            expires_at=serializer.validated_data.get("expires_at"),
        )
        payload = dict(IssuedAPIKeySerializer(api_key).data)
        payload["api_key"] = raw_key
        return Response(payload, status=status.HTTP_201_CREATED)


class DeveloperAPIKeyListAPIView(DeveloperAPIBaseView):
    serializer_class = APIKeyDetailSerializer

    @extend_schema(
        tags=["Developer API Keys"],
        operation_id="developer_api_key_list",
        summary="List API keys",
        description="List API keys belonging to the authenticated developer account.",
        responses={
            200: success_response_schema(
                "DeveloperAPIKeyListSuccessResponse",
                DEVELOPER_API_KEY_LIST_PAYLOAD,
                description="Developer API keys returned successfully.",
            ),
            **standard_error_responses(
                "DeveloperAPIKeyList",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        paginator, page = self.paginate_queryset(self.get_api_key_queryset())
        serializer = self.serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class DeveloperAPIKeyDetailAPIView(DeveloperAPIBaseView):
    serializer_class = APIKeyDetailSerializer

    @extend_schema(
        tags=["Developer API Keys"],
        operation_id="developer_api_key_retrieve",
        summary="Retrieve API key",
        description="Retrieve a single developer API key by UUID.",
        parameters=[
            OpenApiParameter(
                name="id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="API key UUID.",
            )
        ],
        responses={
            200: success_response_schema(
                "DeveloperAPIKeyRetrieveSuccessResponse",
                APIKeyDetailSerializer,
                description="Developer API key returned successfully.",
            ),
            **standard_error_responses(
                "DeveloperAPIKeyRetrieve",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, id):
        serializer = self.serializer_class(self.get_api_key_object())
        return Response(serializer.data)


class DeveloperAPIKeyRegenerateAPIView(DeveloperAPIBaseView):
    serializer_class = IssuedAPIKeySerializer

    @extend_schema(
        tags=["Developer API Keys"],
        operation_id="developer_api_key_regenerate",
        summary="Regenerate API key",
        description="Rotate an API key secret and return the new raw key once.",
        parameters=[
            OpenApiParameter(
                name="id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="API key UUID.",
            )
        ],
        responses={
            200: success_response_schema(
                "DeveloperAPIKeyRegenerateSuccessResponse",
                IssuedAPIKeySerializer,
                description="API key regenerated successfully.",
            ),
            **standard_error_responses(
                "DeveloperAPIKeyRegenerate",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, id):
        api_key, raw_key = regenerate_api_key(self.get_api_key_object())
        payload = dict(IssuedAPIKeySerializer(api_key).data)
        payload["api_key"] = raw_key
        return Response(payload, status=status.HTTP_200_OK)


class DeveloperAPIKeyRevokeAPIView(DeveloperAPIBaseView):
    serializer_class = APIKeyActionResponseSerializer

    @extend_schema(
        tags=["Developer API Keys"],
        operation_id="developer_api_key_revoke",
        summary="Revoke API key",
        description="Revoke an API key so it can no longer be used.",
        parameters=[
            OpenApiParameter(
                name="id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="API key UUID.",
            )
        ],
        responses={
            200: success_response_schema(
                "DeveloperAPIKeyRevokeSuccessResponse",
                APIKeyActionResponseSerializer,
                description="API key revoked successfully.",
            ),
            **standard_error_responses(
                "DeveloperAPIKeyRevoke",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def post(self, request, id):
        api_key = revoke_api_key(self.get_api_key_object())
        return Response({"status": api_key.status}, status=status.HTTP_200_OK)


class DeveloperAPIKeyUsageAPIView(DeveloperAPIBaseView):
    serializer_class = APIUsageLogSerializer

    @extend_schema(
        tags=["Developer API Keys"],
        operation_id="developer_api_key_usage",
        summary="List API key usage",
        description="List usage log entries for a single developer API key.",
        parameters=[
            OpenApiParameter(
                name="id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="API key UUID.",
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
        ],
        responses={
            200: success_response_schema(
                "DeveloperAPIKeyUsageSuccessResponse",
                DEVELOPER_API_USAGE_LIST_PAYLOAD,
                description="API key usage returned successfully.",
            ),
            **standard_error_responses(
                "DeveloperAPIKeyUsage",
                include_401=True,
                include_403=True,
                include_404=True,
            ),
        },
    )
    def get(self, request, id):
        paginator, page = self.paginate_queryset(
            self.get_usage_queryset().filter(api_key=self.get_api_key_object())
        )
        serializer = self.serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class DeveloperAPIUsageAPIView(DeveloperAPIBaseView):
    serializer_class = APIUsageLogSerializer

    @extend_schema(
        tags=["Developer API Keys"],
        operation_id="developer_api_usage_list",
        summary="List developer API usage",
        description="List usage log entries across all API keys belonging to the authenticated developer account.",
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
        ],
        responses={
            200: success_response_schema(
                "DeveloperAPIUsageListSuccessResponse",
                DEVELOPER_API_USAGE_LIST_PAYLOAD,
                description="Developer API usage returned successfully.",
            ),
            **standard_error_responses(
                "DeveloperAPIUsageList",
                include_401=True,
                include_403=True,
            ),
        },
    )
    def get(self, request):
        paginator, page = self.paginate_queryset(self.get_usage_queryset())
        serializer = self.serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)
