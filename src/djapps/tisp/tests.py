from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from djapps.tisp.management.commands.bootstrap_tisp_data import (
    Command as BootstrapTispDataCommand,
)
from djapps.tisp.models import TispApiResponseCache, TispDataValue
from djapps.tisp.services import _normalize_search_query, search_cached_tisp_data


class TispQueryNormalizationTests(SimpleTestCase):
    def test_normalizes_population_wording_and_dodoma_abbreviation(self):
        self.assertEqual(
            _normalize_search_query("number of people in dom"),
            "population dodoma",
        )

    def test_normalizes_swahili_population_query(self):
        self.assertEqual(
            _normalize_search_query("idadi ya watu dom"),
            "population dodoma",
        )

    def test_normalizes_swahili_topic_query(self):
        self.assertEqual(
            _normalize_search_query("kilimo katika Dodoma"),
            "agriculture dodoma",
        )

    def test_normalizes_swahili_sex_breakdown_and_source_request(self):
        self.assertEqual(
            _normalize_search_query(
                "idadi ya watu arusha wanawake na wanaume. na uniambia umetoa wapi hii taarifa"
            ),
            "population arusha female male",
        )

    def test_returns_official_regional_population_breakdown_with_source(self):
        datasets = search_cached_tisp_data(
            "idadi ya watu arusha wanawake na wanaume. na uniambia umetoa wapi hii taarifa"
        )

        self.assertEqual(len(datasets), 1)
        result = datasets[0]
        self.assertEqual(result["region"], "Arusha")
        self.assertIn("2,356,255", result["dataSummary"])
        self.assertIn("1,230,639 (52.2%)", result["dataSummary"])
        self.assertIn("1,125,616 (47.8%)", result["dataSummary"])
        self.assertIn("105,023 more females", result["dataSummary"])
        self.assertIn("Table 3, page 13", result["dataSummary"])
        self.assertTrue(result["sourceUrl"].startswith("https://www.nbs.go.tz/"))

    def test_returns_full_official_zanzibar_population_breakdown(self):
        datasets = search_cached_tisp_data("population in Zanzibar")

        self.assertEqual(len(datasets), 1)
        result = datasets[0]
        self.assertEqual(result["region"], "Tanzania Zanzibar")
        self.assertEqual(
            result["publisher"],
            (
                "National Bureau of Statistics Tanzania and Office of the Chief "
                "Government Statistician Zanzibar"
            ),
        )
        self.assertIn("1,889,773", result["dataSummary"])
        self.assertIn("974,281 (51.6%)", result["dataSummary"])
        self.assertIn("915,492 (48.4%)", result["dataSummary"])
        self.assertIn("963,498 (51.0%)", result["dataSummary"])
        self.assertIn("926,275 (49.0%)", result["dataSummary"])
        self.assertIn("Volume 1C", result["dataSummary"])
        self.assertIn("page vi", result["dataSummary"])
        self.assertIn("sensa.nbs.go.tz", result["dataSummary"])
        self.assertIn("tisp.nbs.go.tz/znz", result["dataSummary"])

    def test_returns_official_tanzania_population_pyramid(self):
        datasets = search_cached_tisp_data(
            "Population Pyramid by Age Group and Sex, Tanzania"
        )

        self.assertEqual(len(datasets), 1)
        result = datasets[0]
        self.assertEqual(
            result["id"],
            "nbs-2022-phc-population-pyramid-tanzania",
        )
        self.assertIn("61,741,120", result["dataSummary"])
        self.assertIn(
            "Age group 0–4: Male 4,723,358, Female 4,760,812, Total 9,484,170",
            result["dataSummary"],
        )
        self.assertIn(
            "Age group 85+: Male 128,504, Female 215,790, Total 344,294",
            result["dataSummary"],
        )
        self.assertIn("42.8%", result["dataSummary"])
        self.assertIn("Median age was 18 years", result["dataSummary"])
        self.assertIn("Table 3.1, page 13", result["dataSummary"])
        self.assertEqual(
            result["searchVisualization"]["type"],
            "population-pyramid",
        )
        self.assertEqual(len(result["searchVisualization"]["labels"]), 18)


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
