from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny

from config.api.responses import StandardizedAPIView, success_response
from config.api.schema import success_response_schema, standard_error_responses
from djapps.tisp.serializers import (
    TispCachedSearchRequestSerializer,
    TispCachedSearchResponseSerializer,
)
from djapps.tisp.services import search_cached_tisp_data


class TispCachedSearchView(StandardizedAPIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=["TISP Cache"],
        operation_id="tisp_cached_search",
        summary="Search cached NBS/TISP data",
        description=(
            "Search NBS/TISP data through the backend cache. The backend stores "
            "external API responses and normalized datavalue rows before "
            "returning datasets to the frontend."
        ),
        auth=[],
        request=TispCachedSearchRequestSerializer,
        responses={
            200: success_response_schema(
                "TispCachedSearchSuccessResponse",
                TispCachedSearchResponseSerializer,
            ),
            **standard_error_responses("TispCachedSearch", include_400=True),
        },
    )
    def post(self, request):
        serializer = TispCachedSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datasets = search_cached_tisp_data(serializer.validated_data["query"])
        return success_response({"datasets": datasets})

