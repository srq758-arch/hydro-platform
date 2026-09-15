"""规则抽取单测：单位归一、年份/口径/范围线索、候选生成与防混淆标记。"""

from __future__ import annotations

from hydro_platform.common.enums import MeasurementScope, PeriodType, ValueType
from hydro_platform.extraction import (
    detect_scope_clue,
    detect_value_type_clue,
    extract_candidates,
    extract_from_text,
    find_years,
    normalize_to_gwh,
    parse_unit,
)
from hydro_platform.parsing.content import ParsedContent, Table
from hydro_platform.common.enums import ContentKind


# ---- 单位 ----

def test_parse_unit_energy_and_power():
    assert parse_unit("GWh").is_energy
    assert parse_unit("MWh").factor_to_gwh == 1e-3
    assert parse_unit("亿千瓦时").factor_to_gwh == 100.0
    # 功率单位识别为容量，不是电量
    up = parse_unit("MW")
    assert up.is_power and not up.is_energy
    # 单位不明
    assert not parse_unit("widgets").is_energy


def test_normalize_to_gwh():
    gwh, up = normalize_to_gwh(1234.0, "MWh")
    assert abs(gwh - 1.234) < 1e-9
    gwh2, _ = normalize_to_gwh(1.5, "亿千瓦时")
    assert abs(gwh2 - 150.0) < 1e-9
    # 功率单位不归一
    none_gwh, up2 = normalize_to_gwh(1200.0, "MW")
    assert none_gwh is None and up2.is_power


# ---- 线索 ----

def test_find_years():
    assert find_years("2023 vs 2024 和 2024 again") == ["2023", "2024"]
    assert find_years("no year 12345 here") == []


def test_value_type_clue_forecast_priority():
    assert detect_value_type_clue("预计发电量").value_type == ValueType.FORECAST
    assert detect_value_type_clue("actual generation").value_type == ValueType.ACTUAL
    assert detect_value_type_clue("全年发电量达到 1118 亿千瓦时").value_type == ValueType.ACTUAL
    # 预测词优先，不能因为同时出现“达到”而误判为实际值。
    assert detect_value_type_clue("预计全年发电量达到 100 亿千瓦时").value_type == ValueType.FORECAST
    assert detect_value_type_clue("发电量 1234 GWh").value_type is None


def test_scope_clue_region_priority():
    assert detect_scope_clue("流域合计发电量").scope == MeasurementScope.REGION
    assert detect_scope_clue("本站发电量").scope == MeasurementScope.PLANT
    assert detect_scope_clue("nothing here").scope is None


# ---- 候选生成 ----

def test_extract_year_near_value():
    cands = extract_from_text("2024 年实际发电量 1,234.5 GWh", entity_id="s1")
    assert len(cands) >= 1
    c = cands[0]
    assert c.period_label == "2024"
    assert abs(c.generation_gwh - 1234.5) < 1e-6
    assert c.value_type == ValueType.ACTUAL
    assert c.entity_id == "s1"
    assert c.extractor == "rule-v1"


def test_extract_mwh_normalized():
    cands = extract_from_text("2023 年发电量 5000 MWh")
    assert abs(cands[0].generation_gwh - 5.0) < 1e-9


def test_power_unit_flagged_not_energy():
    # 1200 MW 是容量，不能当发电量：gwh 应为空并打标记
    cands = extract_from_text("装机容量 1200 MW，2024")
    c = cands[0]
    assert c.generation_gwh is None
    assert "UNIT_NOT_ENERGY" in c.flags
    assert "CAPACITY_SUSPECT" in c.flags


def test_forecast_and_region_flags():
    cands = extract_from_text("2025 年预计流域合计发电量 100 亿千瓦时")
    c = cands[0]
    assert "FORECAST_SUSPECT" in c.flags
    assert "SCOPE_NOT_PLANT" in c.flags
    assert c.value_type == ValueType.FORECAST
    assert c.measurement_scope == MeasurementScope.REGION
    assert abs(c.generation_gwh - 10000.0) < 1e-6  # 100 亿千瓦时 = 10000 GWh


def test_quarter_flag():
    cands = extract_from_text("2024 Q1 发电量 300 GWh")
    c = cands[0]
    assert c.period_type == PeriodType.QUARTER
    assert "PERIOD_QUARTER" in c.flags


def test_year_without_full_year_clue_is_ambiguous():
    candidate = extract_from_text("2024 年完成发电量 802.71 亿千瓦时")[0]
    assert candidate.period_type == PeriodType.CALENDAR_YEAR
    assert "PERIOD_UNCLEAR" in candidate.flags


def test_explicit_full_year_clue_is_not_ambiguous():
    candidate = extract_from_text("2024 年全年完成总发电量 802.71 亿千瓦时")[0]
    assert candidate.period_type == PeriodType.CALENDAR_YEAR
    assert "PERIOD_UNCLEAR" not in candidate.flags


def test_extract_from_parsed_tables():
    table = Table(headers=["Year", "Generation"], rows=[["2023", "1100 GWh"], ["2024", "1234 GWh"]])
    parsed = ParsedContent(kind=ContentKind.HTML, ok=True, text="", tables=[table])
    cands = extract_candidates(parsed, entity_id="s1")
    labels = {c.period_label for c in cands}
    assert "2023" in labels and "2024" in labels
    assert all(c.locator and c.locator.startswith("table[0]") for c in cands)


def test_extracts_target_station_annual_value_from_multilevel_table():
    table = Table(
        headers=[
            "电站名称",
            "2024 年第四季度 总发电量（亿千瓦时）",
            "2024 年全年 总发电量（亿千瓦时）",
        ],
        rows=[
            ["乌东德电站", "84.71", "396.47"],
            ["三峡电站", "143.72", "829.11"],
        ],
    )
    parsed = ParsedContent(kind=ContentKind.HTML, ok=True, text="", tables=[table])
    cands = extract_candidates(
        parsed,
        entity_id="station-wudongde",
        entity_names=("Wudongde hydroelectric plant", "乌东德水电站"),
    )
    annual = [c for c in cands if c.value_raw == "396.47"]
    assert len(annual) == 1
    candidate = annual[0]
    assert candidate.period_label == "2024"
    assert candidate.period_type == PeriodType.CALENDAR_YEAR
    assert candidate.generation_gwh == 39647.0
    assert candidate.locator == "table[0].row[0].col[2]"
    assert "2024 年全年 总发电量" in (candidate.snippet or "")
    assert "三峡" not in (candidate.snippet or "")


def test_failed_parse_yields_no_candidates():
    parsed = ParsedContent.unavailable(ContentKind.PDF, "no pypdf")
    assert extract_candidates(parsed) == []
