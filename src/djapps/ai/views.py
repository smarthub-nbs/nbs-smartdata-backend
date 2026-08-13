from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny

from config.api.responses import StandardizedAPIView, success_response
from config.api.schema import success_response_schema, standard_error_responses
from djapps.ai.serializers import (
    AiSearchAnswerRequestSerializer,
    AiSearchAnswerResponseSerializer,
)
from djapps.ai.services import build_grounded_search_answer


class AiSearchAnswerView(StandardizedAPIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=["AI Search"],
        operation_id="ai_search_answer",
        summary="Generate a grounded AI answer for search results",
        description=(
            "Generate a natural-language answer using only the supplied "
            "NBS/TISP facts and result summaries. Falls back to the deterministic "
            "answer when OpenAI is not configured or unavailable."
        ),
        auth=[],
        request=AiSearchAnswerRequestSerializer,
        responses={
            200: success_response_schema(
                "AiSearchAnswerSuccessResponse",
                AiSearchAnswerResponseSerializer,
            ),
            **standard_error_responses("AiSearchAnswer", include_400=True),
        },
    )
    def post(self, request):
        serializer = AiSearchAnswerRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        answer = build_grounded_search_answer(
            query=payload["query"],
            deterministic_answer=payload["deterministic_answer"],
            facts=payload["facts"],
            results=payload.get("results", []),
        )
        return success_response(answer)

