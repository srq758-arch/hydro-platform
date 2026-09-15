"""候选事实 → 正式 GenerationRecord 的事务性升级（文档 15/16）。

铁律（文档 15）：只有下列条件同时满足才允许进正式排名——
  1. 证据存在（evidence_id 非空且已落库）
  2. Validation 无硬阻断（无 HIGH 级问题；见 has_blocking_issues）
  3. Review approve（若需复核，则复核决策必须为 approve）
  4. 可标 publishable
缺任一条件即拒绝升级，绝不把校验硬阻断/未复核/无证据数据写入正式表。
注意（文档 13.3）：MEDIUM/LOW 级问题（如无法确认 actual/forecast）不是硬阻断，
而是复核触发项——它们会把候选逼进 Review Queue，由人工核准后放行，而非永久拦死。
唯有 HIGH 级（量纲冲突、越界、区域冒充单站、forecast 冒充 actual）才人工也不放行。
generation_gwh 为空的候选不可升级（没有公开数据 ≠ 0，文档 13.3）——保持缺失。
升级按自然键幂等：重复升级同一事实更新而不产生重复行，全过程在单事务内完成。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..common.clock import now_iso
from ..common.enums import PublicationStatus
from ..common.result import ValidationResult
from ..database.connection import transaction
from ..database.repositories import EvidenceRepository, GenerationRepository
from ..models.candidate import ExtractionCandidate
from .promotion_gates import PROMOTION_GATE_VERSION, evaluate_station_annual_generation_gates


class PromotionError(Exception):
    """升级前置条件不满足时抛出——拒绝写入正式表，附原因。"""


@dataclass
class PromotionResult:
    """升级结果：正式记录自然键 + 是否新建。"""

    entity_id: str
    period_type: str
    period_label: str
    value_type: str
    measurement_scope: str
    metric: str
    gate_version: str
    newly_created: bool


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PromotionError(message)


def promote_candidate(
    conn: sqlite3.Connection,
    cand: ExtractionCandidate,
    validation: ValidationResult,
    *,
    evidence_id: str,
    review_approved: bool,
    review_required: bool = True,
) -> PromotionResult:
    """把审核通过的候选事务性升级为正式发电量记录。

    review_required=False 表示该候选无需复核（校验干净且非 Top100）；此时
    review_approved 被忽略。其余前置条件恒需满足。
    """
    # —— 前置条件闸门（文档 15）——
    _require(cand.entity_id is not None, "候选缺 entity_id，无法定位实体")
    _require(cand.period_type is not None, "候选缺 period_type")
    _require(cand.period_label is not None, "候选缺 period_label")
    _require(
        cand.value_type is not None,
        "候选缺 value_type，禁止默认推断为 actual",
    )
    _require(
        cand.measurement_scope is not None,
        "候选缺 measurement_scope，禁止默认推断为 plant",
    )
    _require(
        cand.generation_gwh is not None,
        "generation_gwh 为空不可升级（没有公开数据 ≠ 0）",
    )
    _require(
        not validation.has_blocking_issues,
        "Validation 存在硬阻断问题(HIGH)，不可升级",
    )
    _require(bool(evidence_id), "缺 evidence_id，证据不存在不可升级")

    # 证据必须已落库（证据与正式事实不可脱钩）
    ev_row = EvidenceRepository(conn).get(evidence_id)
    _require(ev_row is not None, f"evidence_id={evidence_id} 未落库")

    gate_report = evaluate_station_annual_generation_gates(
        cand,
        evidence_persisted=ev_row is not None,
        review_satisfied=(not review_required or review_approved),
    )
    if not gate_report.passed:
        failure = gate_report.failures[0]
        raise PromotionError(f"Promotion gate {failure.name} failed: {failure.reason}")

    # 上面的门禁已经保证三项枚举均明确存在。这里禁止使用兜底值，避免把
    # “未知”静默提升为“实际值 / 单站口径”。
    value_type = str(cand.value_type.value)
    scope = str(cand.measurement_scope.value)
    period_type = str(cand.period_type.value)
    metric = str(cand.metric.value)
    key = dict(
        entity_id=cand.entity_id,
        period_type=period_type,
        period_label=cand.period_label,
        value_type=value_type,
        measurement_scope=scope,
    )

    repo = GenerationRepository(conn)
    now = now_iso()
    with transaction(conn):
        existing = repo.get_by_key(**key)
        values = {
            **key,
            "generation_gwh": cand.generation_gwh,
            "metric": metric,
            "normalized_unit": cand.normalized_unit.value,
            "unit_raw": cand.unit_raw,
            "value_raw": cand.value_raw,
            "source_id": cand.source_id,
            "task_id": cand.task_id,
            "evidence_id": evidence_id,
            "candidate_id": cand.candidate_id,
            "confidence": cand.confidence,
            "extractor": cand.extractor,
            "validation_status": "passed" if validation.passed else "passed_with_issues",
            "review_status": "approved" if review_required else "not_required",
            "publication_status": PublicationStatus.PUBLISHABLE.value,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        repo.upsert(values)

    return PromotionResult(
        newly_created=existing is None,
        metric=metric,
        gate_version=PROMOTION_GATE_VERSION,
        **key,
    )
