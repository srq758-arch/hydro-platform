"""Validation 层测试（文档 13）。

验证七类混淆的判定：MW↔GWh、region↔plant、actual↔forecast、fiscal↔calendar、
year 不符、容量-发电量冲突、重复、低置信度进复核；以及 Project 状态/日期冲突。
铁律：generation_gwh=NULL 合法，不因缺失而报错（文档 13.3）。
"""

from __future__ import annotations

from hydro_platform.common.enums import (
    GenerationMetric,
    MeasurementScope,
    NormalizedEnergyUnit,
    PeriodType,
    ProjectStatus,
    Severity,
    ValueType,
)
from hydro_platform.models.candidate import ExtractionCandidate
from hydro_platform.validation import (
    ValidationContext,
    validate_candidate,
    validate_project_record,
)


def _codes(result) -> set[str]:
    return {i.code for i in result.issues}


def _clean_actual(**over) -> ExtractionCandidate:
    base = dict(
        entity_id="e1",
        period_type=PeriodType.CALENDAR_YEAR,
        period_label="2023",
        generation_gwh=100.0,
        metric=GenerationMetric.GROSS_GENERATION,
        normalized_unit=NormalizedEnergyUnit.GWH,
        unit_raw="GWh",
        value_type=ValueType.ACTUAL,
        measurement_scope=MeasurementScope.PLANT,
        confidence=0.9,
        extractor="rule-v1",
    )
    base.update(over)
    return ExtractionCandidate(**base)


def test_clean_actual_plant_candidate_passes():
    res = validate_candidate(_clean_actual())
    assert res.passed
    assert res.issues == []
    assert res.severity == Severity.LOW
    assert "generation_gwh" in res.checked_fields


def test_null_generation_is_allowed():
    # 没有公开数据 ≠ 0：generation_gwh=None 不应触发范围/冲突错误
    res = validate_candidate(_clean_actual(generation_gwh=None))
    assert "VALUE_OUT_OF_RANGE" not in _codes(res)
    assert "CAPACITY_GENERATION_CONFLICT" not in _codes(res)


def test_forecast_flagged_as_mixed():
    res = validate_candidate(_clean_actual(value_type=ValueType.FORECAST))
    assert not res.passed
    assert "ACTUAL_FORECAST_MIXED" in _codes(res)
    assert res.severity == Severity.HIGH


def test_missing_value_type_flagged_medium():
    res = validate_candidate(_clean_actual(value_type=None))
    assert "ACTUAL_FORECAST_MIXED" in _codes(res)


def test_region_scope_flagged_ambiguous():
    res = validate_candidate(_clean_actual(measurement_scope=MeasurementScope.REGION))
    assert "ENTITY_AMBIGUOUS" in _codes(res)


def test_complex_scope_flagged_ambiguous():
    res = validate_candidate(_clean_actual(measurement_scope=MeasurementScope.COMPLEX))
    assert "ENTITY_AMBIGUOUS" in _codes(res)


def test_year_mismatch_detected():
    res = validate_candidate(
        _clean_actual(period_label="2021"),
        ValidationContext(expected_year=2023),
    )
    assert "YEAR_MISMATCH" in _codes(res)


def test_year_match_no_issue():
    res = validate_candidate(
        _clean_actual(period_label="2023 年发电量"),
        ValidationContext(expected_year=2023),
    )
    assert "YEAR_MISMATCH" not in _codes(res)


def test_fiscal_year_flagged():
    res = validate_candidate(_clean_actual(period_type=PeriodType.FISCAL_YEAR))
    assert "YEAR_MISMATCH" in _codes(res)


def test_ambiguous_year_without_full_year_clue_is_flagged():
    cand = _clean_actual(flags=["PERIOD_UNCLEAR"])
    res = validate_candidate(cand)
    assert not res.passed
    assert "PERIOD_AMBIGUOUS" in _codes(res)


def test_unit_not_energy_flag_becomes_capacity_conflict():
    cand = _clean_actual(flags=["UNIT_NOT_ENERGY", "CAPACITY_SUSPECT"])
    res = validate_candidate(cand)
    assert "CAPACITY_GENERATION_CONFLICT" in _codes(res)


def test_unit_unclear_flag_propagates():
    res = validate_candidate(_clean_actual(flags=["UNIT_UNCLEAR"]))
    assert "UNIT_UNCLEAR" in _codes(res)


def test_capacity_generation_conflict_when_exceeds_ceiling():
    # 100 MW 满发上限 ≈ 100*8760/1000*1.15 ≈ 1007 GWh；2000 GWh 明显越界
    res = validate_candidate(
        _clean_actual(generation_gwh=2000.0),
        ValidationContext(entity_capacity_mw=100.0),
    )
    assert "CAPACITY_GENERATION_CONFLICT" in _codes(res)


def test_generation_within_capacity_ceiling_ok():
    res = validate_candidate(
        _clean_actual(generation_gwh=400.0),
        ValidationContext(entity_capacity_mw=100.0),
    )
    assert "CAPACITY_GENERATION_CONFLICT" not in _codes(res)


def test_negative_generation_out_of_range():
    # 直接构造绕过？模型允许 None，但负值由 unit 归一后不该出现；此处显式测校验分支
    cand = _clean_actual()
    cand.generation_gwh = -5.0
    res = validate_candidate(cand)
    assert "VALUE_OUT_OF_RANGE" in _codes(res)


def test_duplicate_record_detected():
    ctx = ValidationContext(
        existing_keys={("2023", ValueType.ACTUAL, MeasurementScope.PLANT)}
    )
    res = validate_candidate(_clean_actual(), ctx)
    assert "DUPLICATE_RECORD" in _codes(res)


def test_low_confidence_flagged_for_review():
    # 文档 13.3：低置信度是通向复核的独立路径，不等于校验失败 → passed 仍为 True
    res = validate_candidate(_clean_actual(confidence=0.3))
    assert "LOW_CONFIDENCE" in _codes(res)
    assert res.passed


# ---- Project 校验 ----

def test_project_clean_passes():
    res = validate_project_record(
        status=ProjectStatus.UNDER_CONSTRUCTION,
        capacity_mw=500.0,
        commissioning_year=None,
    )
    assert res.passed


def test_project_missing_status():
    res = validate_project_record(
        status=None, capacity_mw=1.0, commissioning_year=None
    )
    assert "MISSING_REQUIRED_FIELD" in _codes(res)


def test_project_unknown_status_conflict():
    res = validate_project_record(
        status="demolished", capacity_mw=1.0, commissioning_year=None
    )
    assert "PROJECT_STATUS_CONFLICT" in _codes(res)


def test_project_commissioned_without_year():
    res = validate_project_record(
        status=ProjectStatus.NEWLY_COMMISSIONED,
        capacity_mw=1.0,
        commissioning_year=None,
    )
    assert "PROJECT_DATE_CONFLICT" in _codes(res)


def test_project_commissioned_future_year_conflict():
    res = validate_project_record(
        status=ProjectStatus.NEWLY_COMMISSIONED,
        capacity_mw=1.0,
        commissioning_year=2030,
        current_year=2026,
    )
    assert "PROJECT_DATE_CONFLICT" in _codes(res)


def test_project_negative_capacity():
    res = validate_project_record(
        status=ProjectStatus.APPROVED,
        capacity_mw=-1.0,
        commissioning_year=None,
    )
    assert "VALUE_OUT_OF_RANGE" in _codes(res)
