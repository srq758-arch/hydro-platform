"""Extraction 抽取层（文档 12）。

固定顺序：规则抽取优先 → LLM 补充 → ExtractionCandidate。抽取产物是候选，
不是正式事实，必须再经 Validation/Evidence/Review（文档 12.2）。

本模块本期实装规则抽取（rule_extractors）与 LLM 抽取骨架（llm，接口+prompt+schema
+假 provider，真实调用留待在场验证）。
"""

from .units import UnitParse, normalize_to_gwh, parse_unit
from .patterns import (
    ScopeClue,
    ValueTypeClue,
    detect_scope_clue,
    detect_value_type_clue,
    find_years,
)
from .rule_extractors import extract_candidates, extract_from_text

__all__ = [
    "UnitParse",
    "normalize_to_gwh",
    "parse_unit",
    "ScopeClue",
    "ValueTypeClue",
    "detect_scope_clue",
    "detect_value_type_clue",
    "find_years",
    "extract_candidates",
    "extract_from_text",
]
