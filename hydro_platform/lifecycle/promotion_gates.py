"""Station annual generation Promotion hard gates.

Every decision is explicit and versioned.  Confidence is deliberately absent:
it may rank already-valid candidates, but can never override a failed gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..common.enums import (
    GenerationMetric,
    MeasurementScope,
    NormalizedEnergyUnit,
    PeriodType,
    ValueType,
)
from ..extraction.units import parse_unit
from ..models.candidate import ExtractionCandidate

PROMOTION_GATE_VERSION = "station-annual-generation-v1"


@dataclass(frozen=True)
class GateDecision:
    name: str
    passed: bool
    reason: str
    version: str = PROMOTION_GATE_VERSION


@dataclass(frozen=True)
class PromotionGateReport:
    decisions: tuple[GateDecision, ...]

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.decisions)

    @property
    def failures(self) -> tuple[GateDecision, ...]:
        return tuple(item for item in self.decisions if not item.passed)


def evaluate_station_annual_generation_gates(
    cand: ExtractionCandidate,
    *,
    evidence_persisted: bool,
    review_satisfied: bool,
) -> PromotionGateReport:
    """Evaluate the eight non-bypassable product gates."""
    raw_unit = parse_unit(cand.unit_raw)
    period_is_year = (
        cand.period_type == PeriodType.CALENDAR_YEAR
        and bool(cand.period_label)
        and re.fullmatch(r"(?:19|20)\d{2}", cand.period_label or "") is not None
        and "PERIOD_UNCLEAR" not in cand.flags
    )
    decisions = (
        GateDecision("entity", bool(cand.entity_id), "目标电站已绑定" if cand.entity_id else "缺少目标电站"),
        GateDecision("period", period_is_year, "自然年周期已确认" if period_is_year else "目标不是明确的四位自然年全年周期"),
        GateDecision(
            "metric",
            cand.metric == GenerationMetric.GROSS_GENERATION,
            "总发电量指标已确认" if cand.metric == GenerationMetric.GROSS_GENERATION else "指标不是明确的总发电量",
        ),
        GateDecision(
            "scope",
            cand.measurement_scope == MeasurementScope.PLANT,
            "单站范围已确认" if cand.measurement_scope == MeasurementScope.PLANT else "范围不是明确的单站",
        ),
        GateDecision(
            "value_type",
            cand.value_type == ValueType.ACTUAL,
            "实际值已确认" if cand.value_type == ValueType.ACTUAL else "数值性质不是明确的实际值",
        ),
        GateDecision(
            "unit",
            cand.normalized_unit == NormalizedEnergyUnit.GWH
            and raw_unit.is_energy
            and cand.generation_gwh is not None,
            "能量单位已验证并归一为 GWh"
            if cand.normalized_unit == NormalizedEnergyUnit.GWH and raw_unit.is_energy and cand.generation_gwh is not None
            else "原始能量单位或 GWh 归一结果不完整",
        ),
        GateDecision("evidence", evidence_persisted, "证据链已落库" if evidence_persisted else "证据链未落库"),
        GateDecision("review", review_satisfied, "复核条件已满足" if review_satisfied else "需复核但尚未 approve"),
    )
    return PromotionGateReport(decisions=decisions)
