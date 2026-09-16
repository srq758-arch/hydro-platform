"""年份/口径/范围线索识别（文档 12.3）。

防四类时间与范围混淆：
- 季度当年数据 → 识别 Q1-Q4 / 季度；
- 财年当自然年 → 识别 FY / 财年；
- 预测当实际 → actual/forecast 线索；
- 区域合计当单站 → plant/complex/region 线索。

只产出「线索」，不下最终结论——最终判定在 Validation。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..common.enums import GenerationMetric, MeasurementScope, PeriodType, ValueType

# 4 位年份（1900-2099），避免匹配到 5 位数字
_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_QUARTER_RE = re.compile(r"\b(Q[1-4])\b|第?([一二三四1-4])季度", re.IGNORECASE)
_FISCAL_RE = re.compile(r"\bFY\s?\d{2,4}\b|财年|财政年度|fiscal\s+year", re.IGNORECASE)
# 很多官方年报不写 FY/财年，而用 ``2021/2022``、``2021-2022`` 表示
# 财政年度。该线索不能证明它等同于目标日历年，因此按财年保守处理，
# 让 Validation/Promotion 要求人工确认，而不是静默升格。
_FISCAL_RANGE_RE = re.compile(
    r"\b(?:19|20)\d{2}\s*[/–—-]\s*(?:19|20)\d{2}\b"
)
_MONTH_RE = re.compile(
    r"(?:19|20)\d{2}[-/.年]\s*(?:0?[1-9]|1[0-2])\s*月?|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\b",
    re.IGNORECASE,
)
_YTD_RE = re.compile(
    r"\bytd\b|year[- ]to[- ]date|年初至今|截至.{0,12}(?:累计|发电)", re.IGNORECASE
)
_ROLLING_RE = re.compile(
    r"rolling\s*12\s*months?|trailing\s*12\s*months?|滚动\s*12\s*个?月",
    re.IGNORECASE,
)
_FULL_YEAR_RE = re.compile(
    r"全年|年度|全年度|annual(?:ly)?|anual(?:mente)?|full\s+year|calendar\s+year|yearly",
    re.IGNORECASE,
)

_METRIC_PATTERNS = (
    (GenerationMetric.NET_GENERATION, re.compile(r"净发电量|net\s+(?:electricity\s+)?generation", re.IGNORECASE)),
    (GenerationMetric.ENERGY_SENT_OUT, re.compile(r"上网电量|送出电量|energy\s+sent\s+out|electricity\s+supplied", re.IGNORECASE)),
    (GenerationMetric.ELECTRICITY_SALES, re.compile(r"售电量|electricity\s+sales|power\s+sales", re.IGNORECASE)),
    # “完成发电量”是运营公告对单站实际发电量的常用口径；葡萄牙语
    # 年报中的 geração/produção 也表示电站总产出。若出现净/上网/售电
    # 限定词，前面的专用规则会优先命中，不会被这里覆盖。
    (GenerationMetric.GROSS_GENERATION, re.compile(
        r"总发电量|毛发电量|完成发电量|gross\s+(?:electricity\s+)?generation|"
        r"\b(?:annual\s+)?generation\b|\b(?:energia\s+)?gerad[ao]\b|"
        r"\bgera[cç][aã]o\b|\bprodu[cç][aã]o\b|\bgeneraci[oó]n\b",
        re.IGNORECASE,
    )),
)

_FORECAST_WORDS = (
    "forecast", "projected", "projection", "estimate", "estimated", "expected",
    "planned", "target", "预计", "预测", "计划", "目标", "拟",
)
_ACTUAL_WORDS = (
    "actual", "reported", "recorded", "achieved", "实际", "实发", "累计完成", "已完成",
    "完成", "达到", "实现", "atingiu", "foi de", "realizada", "registrou", "produziu",
)

_REGION_WORDS = (
    "total", "aggregate", "combined", "basin", "cascade", "region", "province",
    "流域", "梯级", "合计", "总计", "全省", "全区", "区域",
)
_COMPLEX_WORDS = ("complex", "power base", "电站群", "基地", "枢纽群")
_GROUP_WORDS = ("group total", "company total", "集团合计", "公司合计", "全公司")
_PLANT_WORDS = (
    "station", "plant", "单站", "本站", "该电站", "电站",
    "usina", "hidrelétrica", "hidreletrica", "hydroelectric",
)


@dataclass
class ValueTypeClue:
    """actual/forecast 线索。value_type 为 None 表示无明确线索。"""

    value_type: ValueType | None = None
    matched: str | None = None


@dataclass
class ScopeClue:
    """单站/电站群/区域线索。scope 为 None 表示无明确线索。"""

    scope: MeasurementScope | None = None
    matched: str | None = None


@dataclass
class MetricClue:
    """指标线索；普通“发电量/generation”不足以证明是总发电量。"""

    metric: GenerationMetric = GenerationMetric.UNKNOWN
    matched: str | None = None


def find_years(text: str) -> list[str]:
    """按出现顺序返回去重后的 4 位年份字符串。"""
    seen: list[str] = []
    for m in _YEAR_RE.finditer(text or ""):
        y = m.group(0)
        if y not in seen:
            seen.append(y)
    return seen


def detect_period_type(text: str) -> PeriodType:
    """据文本判断周期类型；Promotion 会对目标产品再做严格核验。"""
    t = text or ""
    if _ROLLING_RE.search(t):
        return PeriodType.ROLLING_12_MONTHS
    if _YTD_RE.search(t):
        return PeriodType.YEAR_TO_DATE
    if _QUARTER_RE.search(t):
        return PeriodType.QUARTER
    if _FISCAL_RE.search(t):
        return PeriodType.FISCAL_YEAR
    if _FISCAL_RANGE_RE.search(t):
        return PeriodType.FISCAL_YEAR
    if _MONTH_RE.search(t):
        return PeriodType.MONTH
    return PeriodType.CALENDAR_YEAR


def has_explicit_full_year_clue(text: str) -> bool:
    """判断文本是否明确说明自然年全年，而不是仅出现一个四位年份。"""
    return bool(_FULL_YEAR_RE.search(text or ""))


def detect_metric_clue(text: str) -> MetricClue:
    """识别明确指标；没有限定词时返回 UNKNOWN，不把普通发电量猜成总发电量。"""
    for metric, pattern in _METRIC_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return MetricClue(metric=metric, matched=match.group(0))
    return MetricClue()


def _first_hit(text: str, words: tuple[str, ...]) -> str | None:
    low = (text or "").lower()
    for w in words:
        if w.lower() in low:
            return w
    return None


def detect_value_type_clue(text: str) -> ValueTypeClue:
    """识别 actual/forecast 线索。forecast 词优先（宁可保守判预测转人工）。"""
    hit = _first_hit(text, _FORECAST_WORDS)
    if hit:
        return ValueTypeClue(value_type=ValueType.FORECAST, matched=hit)
    hit = _first_hit(text, _ACTUAL_WORDS)
    if hit:
        return ValueTypeClue(value_type=ValueType.ACTUAL, matched=hit)
    return ValueTypeClue()


def detect_scope_clue(text: str) -> ScopeClue:
    """识别单站/电站群/区域线索。区域 > 电站群 > 单站（宁可保守判大范围转人工）。"""
    hit = _first_hit(text, _GROUP_WORDS)
    if hit:
        return ScopeClue(scope=MeasurementScope.GROUP, matched=hit)
    hit = _first_hit(text, _REGION_WORDS)
    if hit:
        return ScopeClue(scope=MeasurementScope.REGION, matched=hit)
    hit = _first_hit(text, _COMPLEX_WORDS)
    if hit:
        return ScopeClue(scope=MeasurementScope.COMPLEX, matched=hit)
    hit = _first_hit(text, _PLANT_WORDS)
    if hit:
        return ScopeClue(scope=MeasurementScope.PLANT, matched=hit)
    return ScopeClue()
