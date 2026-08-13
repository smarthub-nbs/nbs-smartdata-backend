import hashlib
import json
import urllib.parse
import urllib.request
import re
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db import transaction
from django.utils import timezone

from djapps.tisp.models import (
    TispApiResponseCache,
    TispDataValue,
    TispKnowledgeDocument,
    CensusDataRecord,
)


TISP_BASE_URL = "https://tisp.nbs.go.tz:8000"
KNOWN_DATAVALUE_LOOKUPS = (
    {
        "match_terms": ("households", "engaged", "agriculture"),
        "indicator": {
            "indicatorkey": 189000,
            "timeperiodkey": 1460469098,
            "timeperiod_name": "Every Ten year",
            "sector_name": "Agriculture",
            "subsector_name": "Agriculture Engagement",
            "indicator_name": "Households engaged in agriculture, Number",
            "tag": 0,
        },
        "subgroup": {"subgroupkey": 1429736, "subgroup_name": "Maize"},
    },
)


class TispFetchError(Exception):
    pass


def search_cached_tisp_data(query):
    normalized = query.strip().lower()
    if not normalized:
        return []

    lookup = _find_known_lookup(normalized)
    if lookup is None:
        return _search_stored_datavalues(normalized)

    rows = _get_known_datavalues(lookup)
    return [_map_known_lookup_to_dataset(lookup, rows)] if rows else []


def _find_known_lookup(query):
    for lookup in KNOWN_DATAVALUE_LOOKUPS:
        if all(term in query for term in lookup["match_terms"]):
            return lookup
    return None


def _get_known_datavalues(lookup):
    indicator = lookup["indicator"]
    subgroup = lookup["subgroup"]
    rows = list(
        TispDataValue.objects.filter(
            indicatorkey=indicator["indicatorkey"],
            timeperiodkey=indicator["timeperiodkey"],
            subgroupkey=subgroup["subgroupkey"],
        ).order_by("area_level", "area_name")[:12]
    )
    if rows:
        return _prioritize_rows(rows)

    params = {
        "tag": str(indicator["tag"]),
        "timeperiodkey": str(indicator["timeperiodkey"]),
        "indicatorkey": str(indicator["indicatorkey"]),
        "subgroupkey": str(subgroup["subgroupkey"]),
    }
    response = fetch_cached_api_response("datavalue", params)
    if not isinstance(response, list):
        return []

    _store_datavalue_rows(response)
    rows = list(
        TispDataValue.objects.filter(
            indicatorkey=indicator["indicatorkey"],
            timeperiodkey=indicator["timeperiodkey"],
            subgroupkey=subgroup["subgroupkey"],
        ).order_by("area_level", "area_name")[:12]
    )
    return _prioritize_rows(rows)


def fetch_cached_api_response(endpoint, params):
    params_hash = _hash_params(params)
    ttl_seconds = getattr(settings, "TISP_CACHE_TTL_SECONDS", 60 * 60 * 24)
    stale_before = timezone.now() - timedelta(seconds=ttl_seconds)

    cache = TispApiResponseCache.objects.filter(
        endpoint=endpoint,
        params_hash=params_hash,
        fetched_at__gte=stale_before,
    ).first()
    if cache is not None:
        return cache.response

    response = _fetch_tisp_json(endpoint, params)
    TispApiResponseCache.objects.update_or_create(
        endpoint=endpoint,
        params_hash=params_hash,
        defaults={
            "params": params,
            "response": response,
            "fetched_at": timezone.now(),
        },
    )
    return response


def _fetch_tisp_json(endpoint, params):
    url = f"{TISP_BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(
            url,
            timeout=getattr(settings, "TISP_FETCH_TIMEOUT_SECONDS", 20),
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (TimeoutError, OSError, ValueError) as exc:
        raise TispFetchError("TISP request failed") from exc


@transaction.atomic
def _store_datavalue_rows(rows):
    now = timezone.now()
    for row in rows:
        datavaluekey = row.get("datavaluekey")
        if not datavaluekey:
            continue
        TispDataValue.objects.update_or_create(
            datavaluekey=datavaluekey,
            defaults={
                "area_level": row.get("area_level") or "",
                "area_code": row.get("area_code") or "",
                "parent_code": row.get("parent_code") or "",
                "area_name": row.get("area_name") or "",
                "tag": row.get("tag") or 0,
                "areakey": row.get("areakey"),
                "indicatorkey": row.get("indicatorkey") or 0,
                "indicator_name": row.get("indicator_name") or "",
                "datavalue": row.get("datavalue") or row.get("data_value"),
                "time_name": row.get("time_name") or "",
                "source_name": row.get("source_name") or "",
                "source_mda": row.get("source_mda") or "",
                "source_link": row.get("source_link") or "",
                "timeperiod_name": row.get("timeperiod_name") or "",
                "subgroupkey": row.get("subgroupkey"),
                "timeperiodkey": row.get("timeperiodkey"),
                "subgroup_name": row.get("subgroup_name") or "",
                "subgroup_code": row.get("subgroup_code") or "",
                "raw": row,
                "fetched_at": now,
            },
        )


def _search_stored_datavalues(query):
    tokens = [token for token in query.replace(",", " ").split() if len(token) >= 3]
    if not tokens:
        return []

    rows = TispDataValue.objects.all()
    for token in tokens[:5]:
        rows = rows.filter(
            models.Q(indicator_name__icontains=token)
            | models.Q(area_name__icontains=token)
            | models.Q(subgroup_name__icontains=token)
            | models.Q(time_name__icontains=token)
        )
    requested_areas = _requested_area_terms(query)
    if requested_areas:
        area_filter = models.Q()
        for area in requested_areas:
            for area_name in AREA_NAME_ALIASES.get(area, {area}):
                area_filter |= models.Q(area_name__iexact=area_name)
            area_filter |= models.Q(area_code__iexact=area)
        rows = rows.filter(area_filter)

    grouped = {}
    for row in _prioritize_rows(list(rows[:40])):
        key = (row.indicatorkey, row.timeperiodkey, row.subgroupkey)
        grouped.setdefault(key, []).append(row)

    datasets = []
    for group_rows in grouped.values():
        datasets.append(_map_rows_to_dataset(group_rows[:12]))
    census = _search_census_records(tokens, query)
    return [*census, *datasets[:10]][:20]


def _search_census_records(tokens, query=None):
    records = CensusDataRecord.objects.all()
    for token in tokens[:6]:
        records = records.filter(
            models.Q(indicator_name__icontains=token)
            | models.Q(area_name__icontains=token)
            | models.Q(area_code__icontains=token)
            | models.Q(time_name__icontains=token)
        )
    # Use the original query here. Short administrative qualifiers such as
    # “CC” are intentionally omitted from the general search-token list, but
    # they are essential when distinguishing Tanga City Council from Tanga.
    requested_areas = _requested_area_terms(query or " ".join(tokens))
    if requested_areas:
        area_filter = models.Q()
        for area in requested_areas:
            for area_name in AREA_NAME_ALIASES.get(area, {area}):
                area_filter |= models.Q(area_name__iexact=area_name)
            area_filter |= models.Q(area_code__iexact=area)
        records = records.filter(area_filter)
    rows = list(records.order_by("area_level", "area_name")[:20])
    grouped = {}
    for row in _prioritize_census_records(rows):
        grouped.setdefault((row.indicator_name, row.time_name), []).append(row)
    return [_map_census_records(group) for group in grouped.values()]


KNOWN_AREA_NAMES = {
    "tanzania", "mainland", "zanzibar", "arusha", "dar es salaam", "dodoma",
    "mwanza", "mbeya", "morogoro", "tanga", "simiyu", "mara", "kigoma",
    "kilimanjaro", "tabora", "iringa", "mtwara", "lindi", "pwani", "geita",
    "katavi", "rukwa", "singida", "shinyanga", "kagera", "njombe",
    "tanga mjini", "tanga city", "tanga cc", "tanga city council",
}

AREA_NAME_ALIASES = {
    "tanga mjini": {"tanga mjini", "tanga city", "tanga municipal"},
    "tanga city": {"tanga mjini", "tanga city", "tanga municipal"},
    "tanga cc": {"tanga cc", "tanga city council", "tanga city", "tanga mjini"},
    "tanga city council": {"tanga cc", "tanga city council", "tanga city", "tanga mjini"},
}


def _requested_area_terms(query):
    normalized = re.sub(r"[^a-z0-9 ]+", " ", query.lower())
    matched = [
        area for area in sorted(KNOWN_AREA_NAMES, key=len, reverse=True)
        if re.search(rf"(?<![a-z]){re.escape(area)}(?![a-z])", normalized)
    ]
    return [
        area for area in matched
        if not any(
            longer != area and longer.startswith(f"{area} ")
            for longer in matched
        )
    ]


def _prioritize_census_records(rows):
    return sorted(rows, key=lambda row: (0 if row.area_code == "TZ" else 1, row.area_name))


def _map_census_records(rows):
    first = rows[0]
    facts = [
        f"{row.indicator_name} in {row.area_name} was {_format_value(row.data_value)} in {row.time_name}"
        for row in rows[:4]
        if row.data_value is not None
    ]
    summary = "; ".join(facts) + ("." if facts else "")
    return {
        "id": f"tisp-census-{first.indicator_name}-{first.time_name}",
        "title": f"{first.indicator_name} ({first.time_name})",
        "description": summary or "Census map data from the NBS TISP API.",
        "topicSlug": "population" if "population" in first.indicator_name.lower() else "official-statistics",
        "topicName": "Population" if "population" in first.indicator_name.lower() else "Official statistics",
        "format": "JSON", "frequency": "Annual", "region": "National",
        "keywords": ["NBS", "TISP", "census", first.indicator_name, first.time_name],
        "publisher": "National Bureau of Statistics", "updatedAt": first.fetched_at.date().isoformat(),
        "recordCount": len(rows), "license": "Official NBS public data",
        "sourceUrl": f"{TISP_BASE_URL}/census/dmdata/", "dataSummary": summary, "cached": True,
    }


def _search_knowledge_documents(tokens):
    """Return source documentation as dataset-like search results."""
    documents = TispKnowledgeDocument.objects.all()
    for token in tokens[:6]:
        documents = documents.filter(
            models.Q(title__icontains=token) | models.Q(content__icontains=token)
        )

    return [
        {
            "id": f"tisp-knowledge-{document.pk}",
            "title": document.title,
            "description": document.content[:900],
            "topicSlug": "official-statistics",
            "topicName": "Official statistics",
            "format": "JSON" if document.source_type == "api" else "HTML",
            "frequency": "Annual",
            "region": "National",
            "keywords": ["NBS", "Sensa", "TISP", document.source_type],
            "publisher": "National Bureau of Statistics",
            "updatedAt": document.fetched_at.date().isoformat(),
            "recordCount": 1,
            "license": "Official NBS public data",
            "sourceUrl": document.source_url,
            "dataSummary": document.content[:900],
            "cached": True,
        }
        for document in documents[:20]
    ]


def _map_known_lookup_to_dataset(lookup, rows):
    indicator = lookup["indicator"]
    subgroup = lookup["subgroup"]
    return _map_rows_to_dataset(
        rows,
        fallback_indicator=indicator["indicator_name"],
        fallback_sector=indicator["sector_name"],
        fallback_subsector=indicator["subsector_name"],
        fallback_frequency=indicator["timeperiod_name"],
        fallback_subgroup=subgroup["subgroup_name"],
    )


def _map_rows_to_dataset(
    rows,
    *,
    fallback_indicator="",
    fallback_sector="Official statistics",
    fallback_subsector="TISP",
    fallback_frequency="Annual",
    fallback_subgroup="",
):
    first = rows[0]
    indicator = first.indicator_name or fallback_indicator
    subgroup = first.subgroup_name or fallback_subgroup
    summary = _summarize_rows(rows)
    source_url = (
        f"{TISP_BASE_URL}/datavalue?"
        f"tag={first.tag}&timeperiodkey={first.timeperiodkey}"
        f"&indicatorkey={first.indicatorkey}&subgroupkey={first.subgroupkey}"
    )

    return {
        "id": f"external-tisp-db-{first.indicatorkey}-{first.timeperiodkey}-{first.subgroupkey or 'all'}",
        "title": f"{indicator} ({subgroup})" if subgroup else indicator,
        "description": (
            f"{fallback_sector} / {fallback_subsector}. {summary}"
            if summary
            else f"{fallback_sector} / {fallback_subsector}. Cached NBS/TISP data."
        ),
        "topicSlug": _infer_topic(f"{fallback_sector} {indicator} {subgroup}"),
        "topicName": _infer_topic_name(f"{fallback_sector} {indicator} {subgroup}"),
        "format": "JSON",
        "frequency": _to_frequency(first.timeperiod_name or fallback_frequency),
        "region": "National",
        "keywords": [
            "TISP",
            "NBS",
            fallback_sector,
            fallback_subsector,
            indicator,
            subgroup,
            first.time_name,
        ],
        "publisher": "National Bureau of Statistics",
        "updatedAt": timezone.now().date().isoformat(),
        "recordCount": len(rows),
        "license": "Official NBS public data",
        "sourceUrl": source_url,
        "dataSummary": summary,
        "cached": True,
    }


def _summarize_rows(rows):
    facts = []
    for row in rows[:3]:
        if row.datavalue is None:
            continue
        subgroup = f" for {row.subgroup_name}" if row.subgroup_name else ""
        facts.append(
            f"{row.indicator_name}{subgroup} in {row.area_name} "
            f"was {_format_value(row.datavalue)} in {row.time_name}"
        )
    return f"{'; '.join(facts)}." if facts else ""


def _prioritize_rows(rows):
    def priority(row):
        area_code = (row.area_code or "").upper()
        area_name = (row.area_name or "").lower()
        if area_code == "TZ" or area_name == "tanzania":
            return 0
        if area_code == "TZMAIN" or area_name == "mainland":
            return 1
        if area_code == "TZ002" or area_name == "zanzibar":
            return 2
        if row.area_level == "LVL1":
            return 3
        if row.area_level == "LVL2":
            return 4
        return 5

    return sorted(rows, key=lambda row: (priority(row), row.area_name))


def _hash_params(params):
    normalized = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _format_value(value):
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _infer_topic(text):
    normalized = text.lower()
    if any(term in normalized for term in ("agriculture", "crop", "maize", "rice")):
        return "agriculture"
    if any(term in normalized for term in ("population", "census", "household")):
        return "population"
    if any(term in normalized for term in ("gdp", "inflation", "price", "econom")):
        return "economy"
    return "official-statistics"


def _infer_topic_name(text):
    return {
        "agriculture": "Agriculture",
        "population": "Population",
        "economy": "Economy & labour",
    }.get(_infer_topic(text), "Official statistics")


def _to_frequency(value):
    normalized = (value or "").lower()
    if "month" in normalized:
        return "Monthly"
    if "quarter" in normalized:
        return "Quarterly"
    return "Annual"
