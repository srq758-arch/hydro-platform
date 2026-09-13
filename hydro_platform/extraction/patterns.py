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

from ..common.enums import MeasurementScope, PeriodType, ValueType

# 4 位年份（1900-2099），避免匹配到 5 位数字
_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_QUARTER_RE = re.compile(r"\b(Q[1-4])\b|第?([一二三四1-4])季度", re.IGNORECASE)
_FISCAL_RE = re.compile(r"\bFY\s?\d{2,4}\b|财年|财政年度|fiscal\s+year", re.IGNORECASE)

_FORECAST_WORDS = (
    "forecast", "projected", "projection", "estimate", "estimated", "expected",
    "planned", "target", "预计", "预测", "计划", "目标", "拟",
)
_ACTUAL_WORDS = (
    "actual", "reported", "recorded", "achieved", "实际", "实发", "累计完成", "已完成",
)

_REGION_WORDS = (
    "total", "aggregate", "combined", "basin", "cascade", "region", "province",
    "流域", "梯级", "合计", "总计", "全省", "全区", "区域",
)
_COMPLEX_WORDS = ("complex", "power base", "电站群", "基地", "枢纽群")
_PLANT_WORDS = ("station", "plant", "单站", "本站", "该电站", "电站")


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


def find_years(text: str) -> list[str]:
    """按出现顺序返回去重后的 4 位年份字符串。"""
    seen: list[str] = []
    for m in _YEAR_RE.finditer(text or ""):
        y = m.group(0)
        if y not in seen:
            seen.append(y)
    return seen


def detect_period_type(text: str) -> PeriodType:
    """据文本判断周期类型：季度 > 财年 > 自然年（默认）。"""
    t = text or ""
    if _QUARTER_RE.search(t):
        return PeriodType.QUARTER
    if _FISCAL_RE.search(t):
        return PeriodType.FISCAL_YEAR
    return PeriodType.CALENDAR_YEAR


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
