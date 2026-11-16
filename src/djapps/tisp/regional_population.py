"""Official 2022 PHC regional population totals published by NBS Tanzania."""

REGIONAL_POPULATION_SOURCE = {
    "publisher": "National Bureau of Statistics Tanzania",
    "report": (
        "2022 Population and Housing Census: Administrative Units Population "
        "Distribution Report, Tanzania Mainland, Volume 1B"
    ),
    "table": "Table 3",
    "page": 13,
    "year": 2022,
    "url": (
        "https://www.nbs.go.tz/uploads/statistics/documents/"
        "en-1705484561-Administrative_units_Population_Distribution_Report_"
        "Tanzania_Mainland_volume1b.pdf"
    ),
}

ZANZIBAR_POPULATION_SOURCE = {
    "publisher": (
        "National Bureau of Statistics Tanzania and Office of the Chief "
        "Government Statistician Zanzibar"
    ),
    "report": (
        "2022 Population and Housing Census: Administrative Units Population "
        "Distribution Report, Tanzania Zanzibar, Volume 1C"
    ),
    "table": "Tanzania Zanzibar Census Results in Brief",
    "page": "vi",
    "year": 2022,
    "url": (
        "https://www.nbs.go.tz/nbs/takwimu/Census2022/"
        "Administrative_units_Population_Distribution_Report_"
        "Tanzania_Zanzibar_volume1c.pdf"
    ),
    "census_url": "https://sensa.nbs.go.tz/dissemination/results",
    "tisp_url": "https://tisp.nbs.go.tz/znz",
}


# Values are (total, male, female). Keep this table traceable to Table 3 of the
# official report above; do not replace figures with projections.
REGIONAL_POPULATION_2022 = {
    "tanzania mainland": (59_851_347, 29_137_638, 30_713_709),
    "mainland": (59_851_347, 29_137_638, 30_713_709),
    "dodoma": (3_085_625, 1_512_760, 1_572_865),
    "arusha": (2_356_255, 1_125_616, 1_230_639),
    "kilimanjaro": (1_861_934, 907_636, 954_298),
    "tanga": (2_615_597, 1_275_665, 1_339_932),
    "morogoro": (3_197_104, 1_579_869, 1_617_235),
    "pwani": (2_024_947, 998_616, 1_026_331),
    "dar es salaam": (5_383_728, 2_600_018, 2_783_710),
    "lindi": (1_194_028, 582_120, 611_908),
    "mtwara": (1_634_947, 776_782, 858_165),
    "ruvuma": (1_848_794, 902_298, 946_496),
    "iringa": (1_192_728, 574_313, 618_415),
    "mbeya": (2_343_754, 1_123_828, 1_219_926),
    "singida": (2_008_058, 995_703, 1_012_355),
    "tabora": (3_391_679, 1_661_171, 1_730_508),
    "rukwa": (1_540_519, 743_119, 797_400),
    "kigoma": (2_470_967, 1_186_833, 1_284_134),
    "shinyanga": (2_241_299, 1_102_879, 1_138_420),
    "kagera": (2_989_299, 1_459_280, 1_530_019),
    "mwanza": (3_699_872, 1_802_183, 1_897_689),
    "mara": (2_372_015, 1_139_511, 1_232_504),
    "manyara": (1_892_502, 954_879, 937_623),
    "njombe": (889_946, 420_533, 469_413),
    "katavi": (1_152_958, 569_902, 583_056),
    "simiyu": (2_140_497, 1_034_681, 1_105_816),
    "geita": (2_977_608, 1_463_764, 1_513_844),
    "songwe": (1_344_687, 643_679, 701_008),
    "zanzibar": (1_889_773, 915_492, 974_281),
}
