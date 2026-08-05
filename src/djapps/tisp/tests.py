from unittest.mock import patch

from django.test import TestCase

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

