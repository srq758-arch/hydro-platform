"""LLM 抽取骨架测试（文档 12.2）——全程 FakeProvider，零网络。

覆盖：合法 JSON→候选、代码围栏容错、噪声包裹容错、非法/空 JSON→[]、
额外字段被拒（extra=forbid）→[]、MW/forecast/region 标记透传、
provider 确实收到 build_extraction_prompt 生成的 system/user。
"""

from __future__ import annotations

import json

from hydro_platform.common.enums import MeasurementScope, PeriodType, ValueType
from hydro_platform.extraction.llm import FakeProvider, build_extraction_prompt, llm_extract
from hydro_platform.extraction.llm.schema import LLM_EXTRACTOR_VERSION


def _payload(**over) -> str:
    cand = {
        "period_label": "2023",
        "period_type": "calendar_year",
        "generation_gwh": 12.5,
        "value_type": "actual",
        "measurement_scope": "plant",
        "value_raw": "12.5 亿千瓦时",
        "unit_raw": "亿千瓦时",
        "snippet": "2023 年发电量 12.5 亿千瓦时",
        "confidence": 0.8,
    }
    cand.update(over)
    return json.dumps({"candidates": [cand]}, ensure_ascii=False)


def test_valid_json_yields_candidate():
    provider = FakeProvider(_payload())
    out = llm_extract(
        "正文",
        provider,
        entity_id="e1",
        entity_name="某水电站",
        target_period="2023",
        task_id=None,
        source_id="s1",
        locator="p1",
    )
    assert len(out) == 1
    c = out[0]
    assert c.entity_id == "e1"
    assert c.source_id == "s1"
    assert c.locator == "p1"
    assert c.generation_gwh == 12.5
    assert c.period_type == PeriodType.CALENDAR_YEAR
    assert c.extractor == LLM_EXTRACTOR_VERSION
    assert "LLM_SOURCED" in c.flags
    assert "PERIOD_UNCLEAR" in c.flags


def test_llm_full_year_snippet_is_not_period_ambiguous():
    provider = FakeProvider(
        _payload(snippet="2023 年全年总发电量 12.5 亿千瓦时")
    )
    candidate = llm_extract("正文", provider, entity_id="e1")[0]
    assert "PERIOD_UNCLEAR" not in candidate.flags


def test_llm_power_unit_cannot_be_claimed_as_energy():
    candidate = llm_extract(
        "正文",
        FakeProvider(_payload(unit_raw="MW", normalized_unit="gwh")),
        entity_id="e1",
    )[0]
    assert "UNIT_NOT_ENERGY" in candidate.flags
    assert "CAPACITY_SUSPECT" in candidate.flags


def test_llm_missing_unit_is_explicitly_unclear():
    candidate = llm_extract(
        "正文",
        FakeProvider(_payload(unit_raw=None, normalized_unit=None)),
        entity_id="e1",
    )[0]
    assert "UNIT_UNCLEAR" in candidate.flags


def test_code_fence_is_stripped():
    provider = FakeProvider("```json\n" + _payload() + "\n```")
    out = llm_extract("正文", provider, entity_id="e1")
    assert len(out) == 1


def test_surrounding_noise_is_tolerated():
    provider = FakeProvider("这是我的分析结果：\n" + _payload() + "\n以上。")
    out = llm_extract("正文", provider, entity_id="e1")
    assert len(out) == 1


def test_malformed_json_returns_empty():
    provider = FakeProvider("{ this is not valid json ")
    assert llm_extract("正文", provider) == []


def test_no_json_object_returns_empty():
    provider = FakeProvider("抱歉，我无法从中提取数据。")
    assert llm_extract("正文", provider) == []


def test_empty_content_short_circuits_without_calling_provider():
    provider = FakeProvider(_payload())
    assert llm_extract("", provider) == []
    assert provider.calls == []


def test_extra_field_rejected_by_schema():
    # extra="forbid"：多出未知字段应导致整体校验失败 → []
    bad = json.dumps({"candidates": [{"generation_gwh": 1.0, "bogus": "x"}]})
    provider = FakeProvider(bad)
    assert llm_extract("正文", provider) == []


def test_forecast_and_region_flags_propagate():
    provider = FakeProvider(
        _payload(value_type="forecast", measurement_scope="region")
    )
    out = llm_extract("正文", provider, entity_id="e1")
    assert len(out) == 1
    c = out[0]
    assert c.value_type == ValueType.FORECAST
    assert c.measurement_scope == MeasurementScope.REGION
    assert "FORECAST_SUSPECT" in c.flags
    assert "SCOPE_NOT_PLANT" in c.flags


def test_complex_scope_flagged_not_plant():
    provider = FakeProvider(_payload(measurement_scope="complex"))
    out = llm_extract("正文", provider, entity_id="e1")
    assert "SCOPE_NOT_PLANT" in out[0].flags


def test_provider_receives_built_prompt():
    provider = FakeProvider(_payload())
    llm_extract(
        "这里是正文内容",
        provider,
        entity_name="某水电站",
        target_period="2023",
    )
    assert len(provider.calls) == 1
    exp_system, exp_user = build_extraction_prompt(
        "这里是正文内容", entity_name="某水电站", target_period="2023"
    )
    assert provider.calls[0]["system"] == exp_system
    assert provider.calls[0]["user"] == exp_user


def test_empty_candidates_list_is_valid_and_empty():
    provider = FakeProvider(json.dumps({"candidates": []}))
    assert llm_extract("正文", provider, entity_id="e1") == []
