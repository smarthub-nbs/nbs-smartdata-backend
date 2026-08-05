import json
import urllib.error
import urllib.request

from django.conf import settings


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class AiAnswerError(Exception):
    pass


def build_grounded_search_answer(*, query, deterministic_answer, facts, results):
    api_key = getattr(settings, "OPENAI_API_KEY", "")
    model = getattr(settings, "OPENAI_MODEL", "gpt-4.1-mini")

    if not api_key:
        return {
            "answer": deterministic_answer,
            "used_ai": False,
            "model": None,
            "reason": "openai_not_configured",
        }

    if not facts and not results:
        return {
            "answer": deterministic_answer,
            "used_ai": False,
            "model": None,
            "reason": "no_grounding_data",
        }

    prompt = _build_prompt(
        query=query,
        deterministic_answer=deterministic_answer,
        facts=facts,
        results=results,
    )
    payload = {
        "model": model,
        "instructions": (
            "You are the NBS SmartData Hub assistant. Answer using only the "
            "provided NBS/TISP facts and result summaries. Do not invent "
            "numbers, dates, areas, sources, or definitions. If the facts are "
            "not enough, say exactly what is missing. Keep the answer concise "
            "and useful for a public statistics user."
        ),
        "input": prompt,
        "max_output_tokens": 450,
    }

    try:
        response = _post_openai_response(api_key=api_key, payload=payload)
        answer = _extract_response_text(response).strip()
    except AiAnswerError:
        return {
            "answer": deterministic_answer,
            "used_ai": False,
            "model": None,
            "reason": "openai_unavailable",
        }

    if not answer:
        return {
            "answer": deterministic_answer,
            "used_ai": False,
            "model": None,
            "reason": "empty_ai_answer",
        }

    return {
        "answer": answer,
        "used_ai": True,
        "model": model,
        "reason": "",
    }


def _build_prompt(*, query, deterministic_answer, facts, results):
    compact_results = []
    for result in results[:5]:
        compact_results.append(
            {
                "title": result.get("title", ""),
                "description": result.get("description", ""),
                "topic": result.get("topic", ""),
                "region": result.get("region", ""),
                "source_url": result.get("source_url", ""),
                "data_summary": result.get("data_summary", ""),
            }
        )

    grounding = {
        "question": query,
        "fallback_answer": deterministic_answer,
        "facts": facts[:10],
        "results": compact_results,
    }
    return (
        "Write a clear answer to the user's statistics question from this "
        "grounding JSON. Prefer the facts array for numeric claims.\n\n"
        f"{json.dumps(grounding, ensure_ascii=False)}"
    )


def _post_openai_response(*, api_key, payload):
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=getattr(settings, "OPENAI_TIMEOUT_SECONDS", 20),
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
        raise AiAnswerError("OpenAI request failed") from exc


def _extract_response_text(response):
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        return output_text

    chunks = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks)

