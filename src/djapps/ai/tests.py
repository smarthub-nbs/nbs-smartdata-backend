from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from djapps.ai.services import AiAnswerError, build_grounded_search_answer


class AiSearchAnswerServiceTests(SimpleTestCase):
    @override_settings(OPENROUTER_API_KEY="")
    def test_returns_fallback_when_openrouter_is_not_configured(self):
        response = build_grounded_search_answer(
            query="Households engaged in agriculture, Number",
            deterministic_answer="Fallback answer.",
            facts=["Households engaged in agriculture for Maize was 5,404,117."],
            results=[],
        )

        self.assertEqual(response["answer"], "Fallback answer.")
        self.assertFalse(response["used_ai"])
        self.assertEqual(response["reason"], "openrouter_not_configured")

    @override_settings(
        OPENROUTER_API_KEY="test-key",
        OPENROUTER_MODEL="openrouter/free",
    )
    @patch("djapps.ai.services._post_openrouter_chat")
    def test_returns_grounded_openrouter_answer(self, post_chat):
        post_chat.return_value = {
            "model": "example/free-model",
            "choices": [
                {"message": {"content": "The grounded answer."}},
            ],
        }

        response = build_grounded_search_answer(
            query="Households engaged in agriculture, Number",
            deterministic_answer="Fallback answer.",
            facts=["Households engaged in agriculture for Maize was 5,404,117."],
            results=[],
        )

        self.assertEqual(response["answer"], "The grounded answer.")
        self.assertTrue(response["used_ai"])
        self.assertEqual(response["model"], "example/free-model")
        self.assertEqual(response["reason"], "")
        payload = post_chat.call_args.kwargs["payload"]
        self.assertEqual(payload["model"], "openrouter/free")
        self.assertEqual(payload["temperature"], 0.1)
        self.assertEqual(payload["reasoning"], {"enabled": False})
        self.assertEqual(payload["max_tokens"], 1200)
        self.assertEqual(payload["messages"][0]["role"], "system")

    @override_settings(OPENROUTER_API_KEY="test-key")
    @patch("djapps.ai.services._post_openrouter_chat")
    def test_removes_markdown_decoration_from_search_answer(self, post_chat):
        post_chat.return_value = {
            "model": "example/free-model",
            "choices": [
                {
                    "message": {
                        "content": "**Jumla ya watu:** 2,356,255\n\n## Chanzo rasmi"
                    }
                },
            ],
        }

        response = build_grounded_search_answer(
            query="idadi ya watu Arusha",
            deterministic_answer="Fallback answer.",
            facts=["Total population in Arusha Region was 2,356,255 in 2022."],
            results=[],
        )

        self.assertEqual(
            response["answer"],
            "Jumla ya watu: 2,356,255\n\nChanzo rasmi",
        )

    @override_settings(OPENROUTER_API_KEY="test-key")
    @patch("djapps.ai.services._post_openrouter_chat")
    def test_converts_markdown_links_for_the_plain_text_client(self, post_chat):
        post_chat.return_value = {
            "model": "example/free-model",
            "choices": [
                {
                    "message": {
                        "content": (
                            "[Official report](https://example.test/report.pdf)\n"
                            "[https://example.test/data](https://example.test/data)"
                        )
                    }
                }
            ],
        }

        response = build_grounded_search_answer(
            query="population pyramid",
            deterministic_answer="Fallback answer.",
            facts=["A grounded fact."],
            results=[],
        )

        self.assertEqual(
            response["answer"],
            (
                "Official report: https://example.test/report.pdf\n"
                "https://example.test/data"
            ),
        )

    @override_settings(
        OPENROUTER_API_KEY="test-key",
        OPENROUTER_MODEL="openrouter/free",
    )
    @patch("djapps.ai.services._post_openrouter_chat")
    def test_requests_kiswahili_answer_for_swahili_query(self, post_chat):
        post_chat.return_value = {
            "model": "example/free-model",
            "choices": [
                {"message": {"content": "Dodoma ilikuwa na watu 3,085,625."}},
            ],
        }

        response = build_grounded_search_answer(
            query="idadi ya watu Dodoma",
            deterministic_answer="Fallback answer.",
            facts=["Population size in Dodoma was 3,085,625 in 2022."],
            results=[],
        )

        system_prompt = post_chat.call_args.kwargs["payload"]["messages"][0][
            "content"
        ]
        self.assertIn("Respond in clear, natural Kiswahili", system_prompt)
        self.assertTrue(response["used_ai"])

    @override_settings(OPENROUTER_API_KEY="test-key")
    @patch("djapps.ai.services._post_openrouter_chat")
    def test_requests_all_population_breakdowns_and_official_sources(self, post_chat):
        post_chat.return_value = {
            "model": "example/free-model",
            "choices": [{"message": {"content": "Grounded Zanzibar answer."}}],
        }

        build_grounded_search_answer(
            query="population in Zanzibar",
            deterministic_answer="Fallback answer.",
            facts=["Total population in Tanzania Zanzibar was 1,889,773 in 2022."],
            results=[],
        )

        system_prompt = post_chat.call_args.kwargs["payload"]["messages"][0][
            "content"
        ]
        self.assertIn(
            "every supplied sex and place-of-residence breakdown",
            system_prompt,
        )
        self.assertIn("End with an Official sources section", system_prompt)

    @override_settings(OPENROUTER_API_KEY="test-key")
    @patch("djapps.ai.services._post_openrouter_chat")
    def test_requests_every_population_pyramid_age_group(self, post_chat):
        post_chat.return_value = {
            "model": "example/free-model",
            "choices": [{"message": {"content": "Grounded pyramid answer."}}],
        }

        build_grounded_search_answer(
            query="Population Pyramid by Age Group and Sex, Tanzania",
            deterministic_answer="Fallback answer.",
            facts=["Age group 0–4: Male 4,723,358, Female 4,760,812."],
            results=[],
        )

        system_prompt = post_chat.call_args.kwargs["payload"]["messages"][0][
            "content"
        ]
        self.assertIn("include every supplied age group", system_prompt)
        self.assertIn("do not use Markdown tables or Markdown links", system_prompt)

    @override_settings(OPENROUTER_API_KEY="test-key")
    @patch("djapps.ai.services._post_openrouter_chat")
    def test_returns_fallback_when_openrouter_is_unavailable(self, post_chat):
        post_chat.side_effect = AiAnswerError("unavailable")

        response = build_grounded_search_answer(
            query="Population",
            deterministic_answer="Fallback answer.",
            facts=["A grounded fact."],
            results=[],
        )

        self.assertEqual(response["answer"], "Fallback answer.")
        self.assertFalse(response["used_ai"])
        self.assertEqual(response["reason"], "openrouter_unavailable")

    @override_settings(OPENROUTER_API_KEY="test-key")
    @patch("djapps.ai.services._post_openrouter_chat")
    def test_returns_fallback_for_empty_openrouter_answer(self, post_chat):
        post_chat.return_value = {"choices": []}

        response = build_grounded_search_answer(
            query="Population",
            deterministic_answer="Fallback answer.",
            facts=["A grounded fact."],
            results=[],
        )

        self.assertEqual(response["answer"], "Fallback answer.")
        self.assertFalse(response["used_ai"])
        self.assertEqual(response["reason"], "empty_ai_answer")

    @override_settings(OPENROUTER_API_KEY="test-key")
    @patch("djapps.ai.services._post_openrouter_chat")
    def test_skips_openrouter_without_grounding_data(self, post_chat):
        response = build_grounded_search_answer(
            query="Population",
            deterministic_answer="Fallback answer.",
            facts=[],
            results=[],
        )

        self.assertEqual(response["answer"], "Fallback answer.")
        self.assertFalse(response["used_ai"])
        self.assertEqual(response["reason"], "no_grounding_data")
        post_chat.assert_not_called()

