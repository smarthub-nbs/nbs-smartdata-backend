from django.test import SimpleTestCase, override_settings

from djapps.ai.services import build_grounded_search_answer


class AiSearchAnswerServiceTests(SimpleTestCase):
    @override_settings(OPENAI_API_KEY="")
    def test_returns_fallback_when_openai_is_not_configured(self):
        response = build_grounded_search_answer(
            query="Households engaged in agriculture, Number",
            deterministic_answer="Fallback answer.",
            facts=["Households engaged in agriculture for Maize was 5,404,117."],
            results=[],
        )

        self.assertEqual(response["answer"], "Fallback answer.")
        self.assertFalse(response["used_ai"])
        self.assertEqual(response["reason"], "openai_not_configured")

