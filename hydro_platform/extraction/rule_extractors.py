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

from ..common.enums import MeasurementScope, NormalizedEnergyUnit, PeriodType, ValueType
from ..models.candidate import ExtractionCandidate
from ..parsing.content import ParsedContent, Table
from .patterns import (
    detect_period_type,
    detect_metric_clue,
    detect_scope_clue,
    detect_value_type_clue,
    find_years,
    has_explicit_full_year_clue,
)
from .units import parse_unit

RULE_EXTRACTOR_VERSION = "rule-v1"

# 数值 + 紧邻单位，如 "1,234.5 GWh"、"123亿千瓦时"、"1200 MW"
_UNIT_ALT = (
    r"GWh|MWh|kWh|TWh|亿千瓦时|亿度|万千瓦时|万度|千瓦时|兆瓦时|度|"
    r"GW|MW|kW|兆瓦|千瓦|万千瓦"
)
_VALUE_UNIT_RE = re.compile(
    rf"(?P<value>\d[\d.,]*)\s*(?P<unit>{_UNIT_ALT})",
)
# 年份 + 后续数值单位，用于把数值就近关联到年份，如 "2024 年发电量 1234 GWh"
_YEAR_NEAR_RE = re.compile(
    rf"(?P<year>(?:19|20)\d{{2}})\s*年?[^\d]{{0,40}}?"
    rf"(?P<value>\d[\d.,]*)\s*(?P<unit>{_UNIT_ALT})",
)
_CELL_NUMBER_RE = re.compile(r"(?P<value>\d[\d,]*(?:\.\d+)?)")
# 表头里的“季度/年度”包含“度”，不能把这个时间词误识别成能量单位。
# 独立的“度”（如“100 度”）仍可匹配；只排除常见时间复合词的后缀。
_HEADER_UNIT_RE = re.compile(rf"(?<![季度年度月])(?P<unit>{_UNIT_ALT})")
_GENERATION_HEADER_WORDS = ("发电量", "generation", "generated", "output")


def _sentence_context(text: str, start: int, end: int, radius: int = 48) -> str:
    """优先返回数值所在句，避免把相邻段落的“梯级/合计”带入范围判断。"""
    if not text:
        return ""
    separators = "。！？；.!?;"
    left = max((text.rfind(mark, 0, start) for mark in separators), default=-1) + 1
    right_candidates = [text.find(mark, end) for mark in separators]
    right_candidates = [pos for pos in right_candidates if pos >= 0]
    right = min(right_candidates, default=len(text))
    if right - left <= 500:
        return text[left:right + 1].strip()
    return text[max(0, start - radius):min(len(text), end + radius)]


def _infer_document_year(text: str) -> str | None:
    """从标题/公告首段提取文档主年份，供排版错序的 PDF 作为保守回退。"""
    head = (text or "")[:1200]
    match = re.search(
        r"(?P<year>(?:19|20)\d{2})\s*(?:年|年度|annual|year)"
        r"[^。！？.!?]{0,36}(?:发电量|generation|geração|produ[cç][aã]o)",
        head,
        re.IGNORECASE,
    )
    return match.group("year") if match else None


def _document_period_hint(text: str) -> str:
    """提取文档标题/首段的全年口径，供候选共享明确的报告期语义。"""
    head = (text or "")[:1600]
    if re.search(r"全年|年度|annual|anual|full\s+year|calendar\s+year", head, re.IGNORECASE):
        return "年度/全年"
    return ""


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


def _station_row_aliases(entity_names: tuple[str, ...] | None) -> tuple[str, ...]:
    """生成 PDF 线性文本表格可匹配的电站名变体。

    一些 PDF 的表格提取器只能得到类似 ``三峡电站 143.72 -36.47
    829.11 3.29`` 的连续文本，既没有列头，也没有可用的二维表。这里仅
    从目标电站的规范名/当地名生成有限变体，避免在整篇文档中把其它电站
    的数值误归属给当前任务。
    """
    aliases: list[str] = []
    for raw in entity_names or ():
        name = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not name:
            continue
        variants = [name]
        # GEM/本地名有时带河流或“长江”等地理前缀，而公告表格只写短名。
        short = re.sub(r"^(?:长江|金沙江|雅砻江|澜沧江|黄河|珠江|红水河)", "", name)
        if short and short != name:
            variants.append(short)
        # 统一中英文站名后缀，覆盖“三峡水电站”↔“三峡电站”以及
        # “Three Gorges Dam”↔“Three Gorges”、“Belo Monte hydroelectric
        # plant”↔“Belo Monte”。
        for value in tuple(variants):
            for suffix in (
                "水电站", "水电厂", "hydroelectric plant", "hydropower plant",
                "hydroelectric station", "hydropower station", "power plant",
                "power station", "dam", "station",
            ):
                if value.lower().endswith(suffix.lower()):
                    stem = value[: -len(suffix)].strip()
                    if stem:
                        variants.append(
                            stem + ("电站" if suffix in ("水电站", "水电厂") else "")
                        )
                    break
        for value in variants:
            if len(value) >= 2 and value not in aliases:
                aliases.append(value)
    # 长变体优先，避免短名先吃掉长名的一部分。
    return tuple(sorted(aliases, key=len, reverse=True))


def _extract_station_rows_from_text(
    text: str,
    *,
    entity_names: tuple[str, ...] | None,
    entity_id: str | None,
    task_id: str | None,
    source_id: str | None,
    locator: str | None,
) -> list[ExtractionCandidate]:
    """从 PDF 表格的线性文本回退抽取目标电站全年行。

    该回退只在同时满足「目标名称 + 全年/年度表头 + 能量单位 + 五列数值」
    时触发，且只抽取目标行的年度列；季度列和同比列仅用于定位，不会生成
    候选。这样既修复 PDF 版式导致的漏数，也不会把同表其它电站或合计行当成
    当前任务的事实。
    """
    if not text or not entity_names:
        return []
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact or not re.search(
        r"全年|年度|annual|anual|full\s+year|calendar\s+year", compact, re.IGNORECASE
    ):
        return []
    unit_match = _HEADER_UNIT_RE.search(compact)
    if not unit_match:
        return []
    year = _infer_document_year(compact)
    if year is None:
        years = find_years(compact)
        year = years[0] if years else None
    if year is None:
        return []

    out: list[ExtractionCandidate] = []
    aliases = _station_row_aliases(entity_names)
    for alias in aliases:
        # 行结构：站名、季度发电量、季度同比、全年发电量、全年同比。
        # 变化率允许负号和百分号，但只把第四列作为年度发电量。
        pattern = re.compile(
            rf"(?<![\u4e00-\u9fffA-Za-z])(?P<station>{re.escape(alias)})"
            rf"(?![\u4e00-\u9fffA-Za-z])\s+"
            rf"(?P<quarter>-?\d[\d.,]*)\s+"
            rf"(?P<qchange>-?\d[\d.,]*%?)\s+"
            rf"(?P<annual>-?\d[\d.,]*)\s+"
            rf"(?P<annual_change>-?\d[\d.,]*%?)"
        )
        for match in pattern.finditer(compact):
            station = match.group("station")
            annual = match.group("annual")
            context = f"{year}年全年 {station} 完成发电量 {annual} {unit_match.group('unit')}"
            snippet = (
                f"{year}年全年表格行：{station} "
                f"{match.group('quarter')} {match.group('qchange')} {annual} "
                f"{match.group('annual_change')}；全年总发电量 {annual} {unit_match.group('unit')}"
            )
            out.append(
                _build_candidate(
                    year=year,
                    value_str=annual,
                    unit_str=unit_match.group("unit"),
                    context=context,
                    snippet_context=snippet,
                    entity_id=entity_id,
                    task_id=task_id,
                    source_id=source_id,
                    locator=f"{locator or 'text'}.station_row[{station}]",
                )
            )
    # 同一行可能由多个别名命中；按实体/期间/数值/单位去重。
    unique: list[ExtractionCandidate] = []
    seen: set[tuple] = set()
    for candidate in out:
        key = (candidate.period_label, candidate.value_raw, candidate.unit_raw)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _to_float(s: str, context: str = "") -> float | None:
    """解析常见英文/中文小数与葡语/欧洲千位格式。"""
    raw = str(s or "").replace(" ", "")
    if not raw:
        return None
    locale_number = bool(re.search(
        r"(?:produção|geração|usina|relatório|atingiu|suprimento|energia|foram)",
        context or "",
        re.IGNORECASE,
    ))
    if "." in raw and "," in raw:
        # 最后出现的分隔符视为小数点，另一个视为千位分隔。
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif locale_number and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        # 葡萄牙语年报常以 83.879 表示 83,879，而不是 83.879。
        raw = raw.replace(".", "")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    elif raw.count(",") == 1 and len(raw.rsplit(",", 1)[1]) != 3:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        return float(raw)
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
    snippet_context: str | None = None,
    entity_id: str | None,
    task_id: str | None,
    source_id: str | None,
    locator: str | None,
) -> ExtractionCandidate:
    up = parse_unit(unit_str)
    value = _to_float(value_str, context)
    gwh = value * up.factor_to_gwh if (value is not None and up.is_energy and up.factor_to_gwh) else None

    vt_clue = detect_value_type_clue(context)
    scope_clue = detect_scope_clue(context)
    metric_clue = detect_metric_clue(context)
    period_type = detect_period_type(context) if year else None

    flags = _flags_for_unit(up)
    if metric_clue.metric.value == "unknown":
        flags.append("METRIC_UNCLEAR")
    if period_type == PeriodType.QUARTER:
        flags.append("PERIOD_QUARTER")
    if period_type == PeriodType.FISCAL_YEAR:
        flags.append("PERIOD_FISCAL")
    if period_type == PeriodType.CALENDAR_YEAR and year and not has_explicit_full_year_clue(context):
        # 单独出现“2024 年发电量/完成发电量”不能证明是全年值；保留候选，
        # 但交给 Validation/Promotion 强制人工确认，避免阶段性累计值冒充全年。
        flags.append("PERIOD_UNCLEAR")
    if vt_clue.value_type == ValueType.FORECAST:
        flags.append("FORECAST_SUSPECT")
    if scope_clue.scope in (MeasurementScope.REGION, MeasurementScope.COMPLEX):
        flags.append("SCOPE_NOT_PLANT")

    return ExtractionCandidate(
        entity_id=entity_id,
        period_type=period_type,
        period_label=year,
        generation_gwh=gwh,
        metric=metric_clue.metric,
        normalized_unit=NormalizedEnergyUnit.GWH if gwh is not None else None,
        value_type=vt_clue.value_type,
        measurement_scope=scope_clue.scope,
        value_raw=value_str,
        unit_raw=unit_str,
        snippet=(snippet_context if snippet_context is not None else context).strip()[:300] or None,
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
    document_year = _infer_document_year(text)
    document_period = _document_period_hint(text)

    for m in _YEAR_NEAR_RE.finditer(text):
        context = _sentence_context(text, m.start(), m.end())
        classification_context = f"{context} {document_period}".strip()
        candidates.append(
            _build_candidate(
                year=m.group("year"),
                value_str=m.group("value"),
                unit_str=m.group("unit"),
                context=classification_context,
                snippet_context=context,
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
        context = _sentence_context(text, m.start(), m.end())
        classification_context = f"{context} {document_period}".strip()
        nearby_years = [
            match.group(0)
            for match in re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", context)
        ]
        inferred_year = nearby_years[0] if len(set(nearby_years)) == 1 else document_year
        candidates.append(
            _build_candidate(
                year=sole_year or inferred_year,
                value_str=m.group("value"),
                unit_str=m.group("unit"),
                context=classification_context,
                snippet_context=context,
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
    locator_prefix: str | None = None,
) -> list[ExtractionCandidate]:
    out: list[ExtractionCandidate] = []
    table_locator = locator_prefix or f"table[{idx}]"
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
            locator=f"{table_locator}.row[{r}]",
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
                    locator=f"{table_locator}.row[{r}].col[{col}]",
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
    text_locator: str = "text",
) -> list[ExtractionCandidate]:
    """从 ParsedContent 抽取全部候选（正文 + 各表格）。解析失败则返回空列表。"""
    if not parsed.ok:
        return []
    candidates: list[ExtractionCandidate] = []
    candidates.extend(
        extract_from_text(
            parsed.text, entity_id=entity_id, task_id=task_id, source_id=source_id,
            locator=text_locator,
        )
    )
    table_pages = parsed.meta.get("table_pages") if isinstance(parsed.meta, dict) else None
    table_page_spans = parsed.meta.get("table_page_spans") if isinstance(parsed.meta, dict) else None
    for idx, table in enumerate(parsed.tables):
        page_number = table_pages[idx] if isinstance(table_pages, list) and idx < len(table_pages) else None
        page_span = (
            table_page_spans[idx]
            if isinstance(table_page_spans, list) and idx < len(table_page_spans)
            else None
        )
        if isinstance(page_span, (list, tuple)) and len(page_span) == 2 and page_span[0] != page_span[1]:
            locator_prefix = f"page[{page_span[0]}-{page_span[1]}].table[{idx}]"
        else:
            locator_prefix = f"page[{page_number}].table[{idx}]" if page_number else None
        candidates.extend(
            _extract_from_table(
                table,
                idx,
                entity_id=entity_id,
                task_id=task_id,
                source_id=source_id,
                entity_names=entity_names,
                locator_prefix=locator_prefix,
            )
        )
    # PDF 表格经常被解析成“连续文本”而不是二维 Table；在已有正文/表格
    # 候选之后做一次目标行回退，保留可复核定位并避免覆盖原始解析结果。
    candidates.extend(
        _extract_station_rows_from_text(
            parsed.text,
            entity_names=entity_names,
            entity_id=entity_id,
            task_id=task_id,
            source_id=source_id,
            locator=text_locator,
        )
    )
    return candidates
