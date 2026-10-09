from unittest.mock import patch

from django.test import TestCase

from djapps.tisp.management.commands.bootstrap_tisp_data import (
    Command as BootstrapTispDataCommand,
)
from djapps.tisp.models import TispApiResponseCache, TispDataValue
from djapps.tisp.services import search_cached_tisp_data


class TispCachedSearchTests(TestCase):
    @patch("djapps.tisp.services._fetch_tisp_json")
    def test_fetches_stores_and_reuses_known_datavalue_rows(self, fetch_json):
        fetch_json.return_value = [
            {
                "datavaluekey": 437549,
                "area_level": "LVL1",
                "area_code": "TZ",
                "parent_code": None,
                "area_name": "Tanzania",
                "tag": 0,
                "areakey": 1236,
                "indicatorkey": 189000,
                "indicator_name": "Households engaged in agriculture, Number",
                "datavalue": 5404117.0,
                "time_name": "2012",
                "source_name": "Population and Housing Census(PHC)_2012",
                "source_mda": "NBS & OCGS",
                "source_link": None,
                "timeperiod_name": "Every Ten year",
                "subgroupkey": 1429736,
                "timeperiodkey": 1460469098,
                "subgroup_name": "Maize",
                "subgroup_code": "Maize",
            }
        ]

        first = search_cached_tisp_data("Households engaged in agriculture, Number")
        second = search_cached_tisp_data("Households engaged in agriculture, Number")

        self.assertEqual(fetch_json.call_count, 1)
        self.assertEqual(TispApiResponseCache.objects.count(), 1)
        self.assertEqual(TispDataValue.objects.count(), 1)
        self.assertIn("5,404,117", first[0]["dataSummary"])
        self.assertEqual(first, second)


class TispBootstrapCommandTests(TestCase):
    @patch("djapps.tisp.management.commands.bootstrap_tisp_data.call_command")
    @patch.object(BootstrapTispDataCommand, "_cache_is_populated", return_value=False)
    def test_bootstrap_runs_ingest_when_cache_is_empty(
        self,
        cache_is_populated,
        ingest_command,
    ):
        BootstrapTispDataCommand().handle(timeout=45, verbosity=2)

        cache_is_populated.assert_called_once_with()
        ingest_command.assert_called_once_with(
            "ingest_nbs_knowledge",
            timeout=45,
            verbosity=2,
        )

    @patch("djapps.tisp.management.commands.bootstrap_tisp_data.call_command")
    @patch.object(BootstrapTispDataCommand, "_cache_is_populated", return_value=True)
    def test_bootstrap_skips_when_cache_is_present(
        self,
        cache_is_populated,
        ingest_command,
    ):
        BootstrapTispDataCommand().handle()

        cache_is_populated.assert_called_once_with()
        ingest_command.assert_not_called()
