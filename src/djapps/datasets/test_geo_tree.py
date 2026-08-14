from django.test import SimpleTestCase

from djapps.datasets.geo_tree import (
    canonical_geo_parent,
    filter_geo_rows,
    parse_area_levels,
    region_code_from_council,
)


class GeoTreeTests(SimpleTestCase):
    def test_region_code_from_mainland_council(self):
        self.assertEqual(region_code_from_council("10105"), "1")

    def test_region_code_from_island_council(self):
        self.assertEqual(region_code_from_council("25301"), "53")

    def test_lvl5_parent_ignores_tisp_d_key(self):
        self.assertEqual(
            canonical_geo_parent("LVL5", "10105", "D10105"),
            "1",
        )

    def test_filter_keeps_one_area_level(self):
        rows = [
            {"area_name": "Tanzania", "area_level": "LVL1", "area_code": "TZ"},
            {"area_name": "Dodoma", "area_level": "LVL3", "area_code": "1"},
        ]
        filtered = filter_geo_rows(rows, area_levels=parse_area_levels("LVL3"))
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["area_name"], "Dodoma")

    def test_filter_lvl5_parent_from_council_code(self):
        rows = [
            {
                "area_name": "Kondoa",
                "area_level": "LVL5",
                "area_code": "10105",
                "parent_code": "D10105",
            },
            {
                "area_name": "Ilala",
                "area_level": "LVL5",
                "area_code": "10701",
                "parent_code": "D10701",
            },
        ]
        filtered = filter_geo_rows(
            rows,
            area_levels=parse_area_levels("LVL5"),
            parent_code="1",
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["area_name"], "Kondoa")

    def test_filter_localities_by_council_prefix(self):
        rows = [
            {
                "area_name": "Kondoa Mjini",
                "area_level": "LVL7",
                "area_code": "10105011",
            },
            {
                "area_name": "Ilala Mjini",
                "area_level": "LVL7",
                "area_code": "10701011",
            },
        ]
        filtered = filter_geo_rows(
            rows,
            area_levels=parse_area_levels("LVL7"),
            area_code_prefix="10105",
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["area_name"], "Kondoa Mjini")
