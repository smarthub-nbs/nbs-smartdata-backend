"""Official Tanzania 2022 PHC population pyramid data."""

POPULATION_PYRAMID_SOURCE = {
    "publisher": (
        "National Bureau of Statistics Tanzania and Office of the Chief "
        "Government Statistician Zanzibar"
    ),
    "report": "2022 PHC Age and Sex Distribution Report, Tanzania, Volume 2A",
    "table": "Table 3.1",
    "table_page": 13,
    "figure": "Figure 3.1",
    "figure_page": 16,
    "year": 2022,
    "url": (
        "https://www.nbs.go.tz/nbs/takwimu/Census2022/"
        "Age_and_Sex_Distribution_Report_Tanzania_volume2a.pdf"
    ),
    "census_url": "https://sensa.nbs.go.tz/dissemination/results",
}


# Values are (age group, male, female, total), transcribed from Table 3.1.
TANZANIA_AGE_SEX_2022 = (
    ("0–4", 4_723_358, 4_760_812, 9_484_170),
    ("5–9", 4_434_206, 4_484_374, 8_918_580),
    ("10–14", 4_035_586, 3_961_653, 7_997_239),
    ("15–19", 3_096_584, 3_185_807, 6_282_391),
    ("20–24", 2_560_783, 3_005_170, 5_565_953),
    ("25–29", 2_220_550, 2_507_599, 4_728_149),
    ("30–34", 1_902_811, 2_053_126, 3_955_937),
    ("35–39", 1_532_154, 1_676_186, 3_208_340),
    ("40–44", 1_315_193, 1_396_314, 2_711_507),
    ("45–49", 1_121_983, 1_168_062, 2_290_045),
    ("50–54", 906_155, 947_230, 1_853_385),
    ("55–59", 616_934, 636_409, 1_253_343),
    ("60–64", 555_227, 595_851, 1_151_078),
    ("65–69", 329_836, 374_245, 704_081),
    ("70–74", 288_957, 337_915, 626_872),
    ("75–79", 166_374, 207_948, 374_322),
    ("80–84", 117_935, 173_499, 291_434),
    ("85+", 128_504, 215_790, 344_294),
)


def build_tanzania_population_pyramid_dataset():
    source = POPULATION_PYRAMID_SOURCE
    age_facts = [
        f"Age group {age}: Male {male:,}, Female {female:,}, Total {total:,}"
        for age, male, female, total in TANZANIA_AGE_SEX_2022
    ]
    summary = "; ".join(
        (
            "Total population in Tanzania was 61,741,120 in 2022",
            "Male population in Tanzania was 30,053,130 (48.7%) in 2022",
            "Female population in Tanzania was 31,687,990 (51.3%) in 2022",
            *age_facts,
            "Population below age 15 was 42.8%",
            "Median age was 18 years",
            "Population aged 65 years and above was 3.8%",
            (
                f"Official source: {source['report']}, {source['table']}, "
                f"page {source['table_page']}; {source['figure']}, "
                f"page {source['figure_page']}"
            ),
            f"Official report URL: {source['url']}",
            f"NBS Census Dissemination Platform: {source['census_url']}",
        )
    ) + "."

    return {
        "id": "nbs-2022-phc-population-pyramid-tanzania",
        "title": "Population pyramid by age group and sex — Tanzania, 2022 PHC",
        "description": (
            "Official Tanzania population distribution by five-year age group "
            "and sex from the 2022 Population and Housing Census."
        ),
        "topicSlug": "population",
        "topicName": "Population",
        "format": "PDF",
        "frequency": "Every ten years",
        "region": "Tanzania",
        "keywords": [
            "NBS",
            "OCGS",
            "census",
            "population",
            "pyramid",
            "age group",
            "sex",
            "male",
            "female",
            "2022",
            "Tanzania",
        ],
        "publisher": source["publisher"],
        "updatedAt": "2022-12-17",
        "recordCount": len(TANZANIA_AGE_SEX_2022),
        "license": "Official NBS public data",
        "sourceUrl": source["url"],
        "dataSummary": summary,
        "searchVisualization": {
            "type": "population-pyramid",
            "labels": [row[0] for row in TANZANIA_AGE_SEX_2022],
            "male": [row[1] for row in TANZANIA_AGE_SEX_2022],
            "female": [row[2] for row in TANZANIA_AGE_SEX_2022],
        },
        "cached": True,
    }
