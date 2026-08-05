import json
import re
import urllib.error
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand
from django.utils import timezone

from djapps.tisp.models import CensusDataRecord, TispApiResponseCache, TispKnowledgeDocument
from djapps.tisp.services import _store_datavalue_rows, _hash_params


SENSA_PAGES = (
    "introduction", "api-basics", "sectors", "sub-sectors", "indicators",
    "sub-groups", "area", "indicator-values",
)

TISP_URLS = (
    "/census/data/",
    "/census/dmdata/",
    "/census/data/?indicator_short_name=TZ_IND_007,TZ_IND_403",
    "/census/data/?indicator_short_name=TZ_IND_007,TZ_IND_403&subgroup_short_name=Total,Male,Female",
    "/census/data/?indicator_short_name=TZ_IND_007,TZ_IND_403&time_value=2022,2012",
    "/census/data/?indicator_short_name=TZ_IND_007,TZ_IND_403&area_code=TZ,TZMAIN",
    "/census/data/?indicator_short_name=TZ_IND_007,TZ_IND_403&parent_code=TZ",
    "/census/data/?indicator_short_name=TZ_IND_007,TZ_IND_403&tag=1,2",
    "/census/area/?area_code=TZ", "/census/area/?parent_code=TZ", "/census/area/",
    "/census/subgroup/", "/census/indicator/", "/census/subsector/", "/census/sector/",
    "/census/sector/?sector_short_name=TZ_SEC_003",
    "/census/subsector/?subsector_short_name=TZ_SUBSEC_006,TZ_SUBSEC_009",
)


class Command(BaseCommand):
    help = "Snapshot the NBS Sensa documentation and TISP API data locally."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=30)

    def handle(self, *args, **options):
        timeout = options["timeout"]
        ok = failed = 0
        for slug in SENSA_PAGES:
            url = f"https://sensa.nbs.go.tz/data-sharing/{slug}"
            if self._ingest(url, "documentation", timeout):
                ok += 1
            else:
                failed += 1
        for path in TISP_URLS:
            url = f"https://tisp.nbs.go.tz:8000{path}"
            if self._ingest(url, "api", timeout):
                ok += 1
            else:
                failed += 1
        self.stdout.write(self.style.SUCCESS(f"Ingested {ok} sources; {failed} failed."))

    def _ingest(self, url, source_type, timeout):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "NBS-SmartData/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            self.stderr.write(f"Skipped {url}: {exc}")
            return False

        payload = self._parse_json(body) if source_type == "api" else {}
        content = self._text(body) if source_type == "documentation" else self._json_text(payload)
        title = self._title(url, body, source_type)
        TispKnowledgeDocument.objects.update_or_create(
            source_url=url,
            defaults={"source_type": source_type, "title": title, "content": content[:100000], "payload": payload, "fetched_at": timezone.now()},
        )
        if source_type == "api":
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            endpoint = urllib.parse.urlsplit(url).path.removeprefix("/census/").strip("/") or "root"
            TispApiResponseCache.objects.update_or_create(
                endpoint=endpoint, params_hash=_hash_params(params),
                defaults={"params": params, "response": payload, "fetched_at": timezone.now()},
            )
            rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
            if isinstance(rows, list):
                self._store_rows(endpoint, rows)
        self.stdout.write(f"Saved {url}")
        return True

    @staticmethod
    def _store_rows(endpoint, rows):
        data_value_rows = [row for row in rows if isinstance(row, dict) and row.get("datavaluekey")]
        if data_value_rows:
            _store_datavalue_rows(data_value_rows)
        if endpoint == "dmdata":
            now = timezone.now()
            for row in rows:
                if not isinstance(row, dict) or not row.get("indicator_name"):
                    continue
                key = "|".join(str(row.get(field, "")) for field in ("indicator_name", "area_code", "time_name"))
                CensusDataRecord.objects.update_or_create(
                    record_key=key[:160],
                    defaults={
                        "area_name": row.get("area_name") or "", "area_code": str(row.get("area_code") or ""),
                        "area_level": row.get("area_level") or "", "parent_code": str(row.get("parent_code") or ""),
                        "indicator_name": row.get("indicator_name") or "", "time_name": row.get("time_name") or "",
                        "data_value": row.get("data_value"), "tag": row.get("area_tag") or 0, "raw": row, "fetched_at": now,
                    },
                )

    @staticmethod
    def _parse_json(body):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"_raw": body[:10000]}

    @staticmethod
    def _text(body):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()

    @staticmethod
    def _json_text(payload):
        return json.dumps(payload, ensure_ascii=False)[:100000]

    @staticmethod
    def _title(url, content, source_type):
        if source_type == "documentation":
            match = re.search(r"<title>(.*?)</title>", content, re.I)
            return match.group(1).strip() if match else url.rsplit("/", 1)[-1].replace("-", " ").title()
        return f"NBS TISP API: {url.split('/census/', 1)[-1]}"
