from hydro_platform.common.enums import GenerationMetric, MeasurementScope, PeriodType
from hydro_platform.extraction.patterns import (
    detect_metric_clue,
    detect_period_type,
    detect_scope_clue,
)
from hydro_platform.extraction.rule_extractors import extract_from_text


def test_metric_ontology_does_not_guess_plain_generation():
    assert detect_metric_clue("2024年发电量为100亿千瓦时").metric == GenerationMetric.UNKNOWN
    assert detect_metric_clue("2024年总发电量为100亿千瓦时").metric == GenerationMetric.GROSS_GENERATION
    assert detect_metric_clue("2024年上网电量为90亿千瓦时").metric == GenerationMetric.ENERGY_SENT_OUT


def test_period_and_scope_ontology_separate_ytd_and_group():
    assert detect_period_type("截至2024年9月累计发电") == PeriodType.YEAR_TO_DATE
    assert detect_period_type("rolling 12 months") == PeriodType.ROLLING_12_MONTHS
    assert detect_period_type("Annual report 2021/2022 generated energy") == PeriodType.FISCAL_YEAR
    assert detect_period_type("财政年度 2021-2022 发电量") == PeriodType.FISCAL_YEAR
    assert detect_scope_clue("集团合计发电量").scope == MeasurementScope.GROUP


def test_rule_candidate_records_metric_and_normalized_unit():
    candidates = extract_from_text("该电站2024年实际总发电量达到12.3亿千瓦时")
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.metric == GenerationMetric.GROSS_GENERATION
    assert candidate.normalized_unit.value == "gwh"
    assert candidate.generation_gwh == 1230.0
