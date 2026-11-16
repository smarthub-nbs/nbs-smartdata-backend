import json
import re
import urllib.error
import urllib.request

from django.conf import settings


class AiAnswerError(Exception):
    pass


def build_grounded_search_answer(*, query, deterministic_answer, facts, results):
    api_key = getattr(settings, "OPENROUTER_API_KEY", "")
    model = getattr(settings, "OPENROUTER_MODEL", "openrouter/free")

    if not api_key:
        return {
            "answer": deterministic_answer,
            "used_ai": False,
            "model": None,
            "reason": "openrouter_not_configured",
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
    language_instruction = (
        "Respond in clear, natural Kiswahili because the user's question is in "
        "Kiswahili. Preserve official dataset names when translating them could "
        "cause ambiguity. In statistical answers, translate 'Population size' "
        "as 'idadi ya watu', not 'ukubwa wa jamii'."
        if _detect_response_language(query) == "sw"
        else "Respond in English."
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the NBS SmartData Hub assistant. Answer using only "
                    "the supplied NBS/TISP facts and dataset summaries. Never "
                    "invent numbers, dates, areas, sources, or definitions. If "
                    "the supplied information cannot answer the question, state "
                    "exactly what information is missing. Keep the answer concise "
                    "and useful for a public statistics user. NBS means the "
                    "National Bureau of Statistics of Tanzania; never expand NBS "
                    "to a different organization name. When official source "
                    "metadata is supplied, identify the report, table/page, year, "
                    "and source URL. For population questions, present the total "
                    "and every supplied sex and place-of-residence breakdown; do "
                    "not say a breakdown is unavailable when it is present in the "
                    "grounding. For population-pyramid or age-and-sex questions, "
                    "include every supplied age group with its male, female, and "
                    "total values, followed by the supplied key findings. Put each "
                    "age group on its own plain-text line; do not use Markdown "
                    "tables or Markdown links because the client displays plain text. "
                    "Calculate percentages or differences only from "
                    "supplied values. Use short readable sections for totals, "
                    "breakdowns, comparisons, and sources. End with an Official "
                    "sources section whenever official source metadata is supplied. "
                    f"{language_instruction}"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "reasoning": {"enabled": False},
        "max_tokens": 1200,
    }

    try:
        response = _post_openrouter_chat(api_key=api_key, payload=payload)
        answer = _to_plain_text(_extract_response_text(response)).strip()
    except AiAnswerError:
        return {
            "answer": deterministic_answer,
            "used_ai": False,
            "model": None,
            "reason": "openrouter_unavailable",
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
        "model": response.get("model") or model,
        "reason": "",
    }


def _detect_response_language(query):
    query_words = set(re.findall(r"[a-z]+", query.lower()))
    swahili_markers = {
        "idadi",
        "watu",
        "wakazi",
        "wangapi",
        "takwimu",
        "mkoa",
        "mwaka",
        "kilimo",
        "afya",
        "elimu",
        "uchumi",
        "sensa",
        "maji",
        "utalii",
        "wanawake",
        "wanaume",
        "chanzo",
        "taarifa",
    }
    return "sw" if query_words & swahili_markers else "en"


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
        "Write a clear, evidence-backed answer to the user's statistics question "
        "from this grounding JSON. Prefer the facts array for numeric claims. "
        "If the user asks where the information came from, include every source "
        "detail present in the result and its official URL. Do not mention a "
        "source, page, table, or statistic that is absent from the grounding.\n\n"
        f"{json.dumps(grounding, ensure_ascii=False)}"
    )


def _post_openrouter_chat(*, api_key, payload):
    base_url = getattr(
        settings,
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
    ).rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    site_url = getattr(settings, "OPENROUTER_SITE_URL", "").strip()
    app_name = getattr(settings, "OPENROUTER_APP_NAME", "").strip()
    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_name:
        headers["X-Title"] = app_name

    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=getattr(settings, "OPENROUTER_TIMEOUT_SECONDS", 30),
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
        raise AiAnswerError("OpenRouter request failed") from exc


def _extract_response_text(response):
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    return content if isinstance(content, str) else ""


def _to_plain_text(answer):
    """Remove lightweight Markdown decoration unsupported by the search UI."""
    answer = answer.replace("**", "").replace("__", "")
    answer = re.sub(r"(?m)^#{1,6}\s*", "", answer)
    answer = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda match: (
            match.group(2)
            if match.group(1) == match.group(2)
            else f"{match.group(1)}: {match.group(2)}"
        ),
        answer,
    )
    return answer

