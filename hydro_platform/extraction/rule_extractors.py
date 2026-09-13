"""规则抽取器（文档 12.1）。

从解析后的文本/表格里，用正则 + 单位模式抽出「年份—数值—单位」候选，归一到 GWh，
并附带 actual/forecast 与单站/区域线索。产出 ExtractionCandidate（候选，非正式事实）。

保守原则（文档 12.3 / 13.3）：
- 功率单位不当作发电量：归一失败并打 UNIT_NOT_ENERGY / CAPACITY_SUSPECT 标记；
- 单位不明不猜测：generation_gwh 留空并打 UNIT_UNCLEAR；
- 识别到季度/财年/预测/区域线索时打标记，交 Validation 决定是否转人工。
"""

from __future__ import annotations

import re

from ..common.enums import MeasurementScope, PeriodType, ValueType
from ..models.candidate import ExtractionCandidate
from ..parsing.content import ParsedContent, Table
from .patterns import (
    detect_period_type,
    detect_scope_clue,
    detect_value_type_clue,
    find_years,
)
from .units import parse_unit

RULE_EXTRACTOR_VERSION = "rule-v1"

# 数值 + 紧邻单位，如 "1,234.5 GWh"、"123亿千瓦时"、"1200 MW"
_UNIT_ALT = (
    r"GWh|MWh|kWh|TWh|亿千瓦时|亿度|万千瓦时|万度|千瓦时|兆瓦时|度|"
    r"GW|MW|kW|兆瓦|千瓦|万千瓦"
)
_VALUE_UNIT_RE = re.compile(
    rf"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>{_UNIT_ALT})",
)
# 年份 + 后续数值单位，用于把数值就近关联到年份，如 "2024 年发电量 1234 GWh"
_YEAR_NEAR_RE = re.compile(
    rf"(?P<year>(?:19|20)\d{{2}})\s*年?[^\d]{{0,40}}?"
    rf"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>{_UNIT_ALT})",
)
_CELL_NUMBER_RE = re.compile(r"(?P<value>\d[\d,]*(?:\.\d+)?)")
_HEADER_UNIT_RE = re.compile(rf"(?P<unit>{_UNIT_ALT})")
_GENERATION_HEADER_WORDS = ("发电量", "generation", "generated", "output")


def _normalise_station_name(value: str) -> str:
    """为表格行匹配生成保守的中英文站名键。"""
    text = "".join(ch for ch in (value or "").lower() if ch.isalnum())
    for suffix in (
        "hydroelectricplant", "hydropowerplant", "hydroelectricstation",
        "hydropowerstation", "powerplant", "powerstation", "水电站", "水电厂", "电站",
    ):
        text = text.replace(suffix, "")
    return text


def _matches_target_station(row_label: str, entity_names: tuple[str, ...] | None) -> bool:
    """有目标名称时，只抽取目标电站所在行，杜绝把同表其它站的数值归属给目标站。"""
    if not entity_names:
        return True
    row_key = _normalise_station_name(row_label)
    if len(row_key) < 3:
        return False
    for name in entity_names:
        name_key = _normalise_station_name(name)
        if len(name_key) >= 3 and (name_key in row_key or row_key in name_key):
            return True
    return False


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _flags_for_unit(up) -> list[str]:
    if up.is_power:
        return ["UNIT_NOT_ENERGY", "CAPACITY_SUSPECT"]
    if not up.is_energy:
        return ["UNIT_UNCLEAR"]
    return []


def _build_candidate(
    *,
    year: str | None,
    value_str: str,
    unit_str: str,
    context: str,
    entity_id: str | None,
    task_id: str | None,
    source_id: str | None,
    locator: str | None,
) -> ExtractionCandidate:
    up = parse_unit(unit_str)
    value = _to_float(value_str)
    gwh = value * up.factor_to_gwh if (value is not None and up.is_energy and up.factor_to_gwh) else None

    vt_clue = detect_value_type_clue(context)
    scope_clue = detect_scope_clue(context)
    period_type = detect_period_type(context) if year else None

    flags = _flags_for_unit(up)
    if period_type == PeriodType.QUARTER:
        flags.append("PERIOD_QUARTER")
    if period_type == PeriodType.FISCAL_YEAR:
        flags.append("PERIOD_FISCAL")
    if vt_clue.value_type == ValueType.FORECAST:
        flags.append("FORECAST_SUSPECT")
    if scope_clue.scope in (MeasurementScope.REGION, MeasurementScope.COMPLEX):
        flags.append("SCOPE_NOT_PLANT")

    return ExtractionCandidate(
        entity_id=entity_id,
        period_type=period_type,
        period_label=year,
        generation_gwh=gwh,
        value_type=vt_clue.value_type,
        measurement_scope=scope_clue.scope,
        value_raw=value_str,
        unit_raw=unit_str,
        snippet=context.strip()[:300] or None,
        locator=locator,
        confidence=None,
        extractor=RULE_EXTRACTOR_VERSION,
        task_id=task_id,
        source_id=source_id,
        flags=flags,
    )


def extract_from_text(
    text: str,
    *,
    entity_id: str | None = None,
    task_id: str | None = None,
    source_id: str | None = None,
    locator: str | None = None,
) -> list[ExtractionCandidate]:
    """从纯文本抽取候选。优先「年份+就近数值单位」，再补「孤立数值单位」。"""
    if not text:
        return []
    candidates: list[ExtractionCandidate] = []
    consumed_spans: list[tuple[int, int]] = []

    for m in _YEAR_NEAR_RE.finditer(text):
        start = max(0, m.start() - 30)
        end = min(len(text), m.end() + 30)
        candidates.append(
            _build_candidate(
                year=m.group("year"),
                value_str=m.group("value"),
                unit_str=m.group("unit"),
                context=text[start:end],
                entity_id=entity_id,
                task_id=task_id,
                source_id=source_id,
                locator=locator,
            )
        )
        consumed_spans.append((m.start("value"), m.end("unit")))

    years = find_years(text)
    sole_year = years[0] if len(years) == 1 else None
    for m in _VALUE_UNIT_RE.finditer(text):
        span = (m.start(), m.end())
        if any(s <= span[0] < e for s, e in consumed_spans):
            continue
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + 40)
        candidates.append(
            _build_candidate(
                year=sole_year,
                value_str=m.group("value"),
                unit_str=m.group("unit"),
                context=text[start:end],
                entity_id=entity_id,
                task_id=task_id,
                source_id=source_id,
                locator=locator,
            )
        )
    return candidates


def _extract_from_table(
    table: Table,
    idx: int,
    *,
    entity_id: str | None,
    task_id: str | None,
    source_id: str | None,
    entity_names: tuple[str, ...] | None = None,
) -> list[ExtractionCandidate]:
    out: list[ExtractionCandidate] = []
    header_text = " ".join(table.headers or [])
    for r, row in enumerate(table.rows):
        row_text = " ".join(row)
        context = f"{header_text} {row_text}"
        # 行内若含年份+数值单位或孤立数值单位，走文本抽取逻辑，locator 记表格坐标
        subs = extract_from_text(
            context,
            entity_id=entity_id,
            task_id=task_id,
            source_id=source_id,
            locator=f"table[{idx}].row[{r}]",
        )
        out.extend(subs)

        # HTML 年度表常把单位和年份写在多级表头、把数值单独放在单元格。普通正则
        # 无法把两者关联，因此按「目标站行 × 发电量列」直接构造候选及可复核摘要。
        if not table.headers or not row or not _matches_target_station(row[0], entity_names):
            continue
        for col, cell in enumerate(row):
            if col >= len(table.headers):
                break
            header = table.headers[col]
            header_lower = header.lower()
            if not any(word in header_lower for word in _GENERATION_HEADER_WORDS):
                continue
            if any(word in header_lower for word in ("同比", "增长", "change", "growth", "%")):
                continue
            # 季度列不能冒充全年发电量；全年/年度或不含季度线索的列才保留。
            if detect_period_type(header) == PeriodType.QUARTER:
                continue
            unit_match = _HEADER_UNIT_RE.search(header)
            value_match = _CELL_NUMBER_RE.search(cell.replace(" ", ""))
            years = find_years(header) or find_years((table.caption or "") + " " + header_text)
            if not unit_match or not value_match or not years:
                continue
            context = (
                f"表格 {idx + 1}" + (f"（{table.caption}）" if table.caption else "")
                + f"：电站名称={row[0]}；{header}={value_match.group('value')} {unit_match.group('unit')}"
            )
            out.append(
                _build_candidate(
                    year=years[0],
                    value_str=value_match.group("value"),
                    unit_str=unit_match.group("unit"),
                    context=context,
                    entity_id=entity_id,
                    task_id=task_id,
                    source_id=source_id,
                    locator=f"table[{idx}].row[{r}].col[{col}]",
                )
            )
    return out


def extract_candidates(
    parsed: ParsedContent,
    *,
    entity_id: str | None = None,
    task_id: str | None = None,
    source_id: str | None = None,
    entity_names: tuple[str, ...] | None = None,
) -> list[ExtractionCandidate]:
    """从 ParsedContent 抽取全部候选（正文 + 各表格）。解析失败则返回空列表。"""
    if not parsed.ok:
        return []
    candidates: list[ExtractionCandidate] = []
    candidates.extend(
        extract_from_text(
            parsed.text, entity_id=entity_id, task_id=task_id, source_id=source_id,
            locator="text",
        )
    )
    for idx, table in enumerate(parsed.tables):
        candidates.extend(
            _extract_from_table(
                table,
                idx,
                entity_id=entity_id,
                task_id=task_id,
                source_id=source_id,
                entity_names=entity_names,
            )
        )
    return candidates
