"""人工复核队列（文档 15）。

判定「必须进复核」的条件（文档 15）：低置信度、校验失败、多源冲突、
实体匹配不确定、年份/单位不清、Top100 相关、关键项目状态变化。
入队幂等（按事实键），决策统一为 approve/reject/request_more_evidence。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from ..common.enums import ReviewDecision, Severity
from ..common.result import ValidationResult
from ..database.repositories import ReviewRepository
from ..models.candidate import ExtractionCandidate
from ..models.evidence import FACT_TYPE_GENERATION, make_generation_fact_key
from ..pipeline.approval_versioning import compute_persisted_candidate_hash

# 触发复核的问题码（除「整体未通过/高危」外的显式清单，便于测试与审计）
_REVIEW_TRIGGER_CODES = frozenset(
    {
        "LOW_CONFIDENCE",
        "ENTITY_AMBIGUOUS",
        "UNIT_UNCLEAR",
        "YEAR_MISMATCH",
        "PERIOD_AMBIGUOUS",
        "ACTUAL_FORECAST_MIXED",
        "CAPACITY_GENERATION_CONFLICT",
        "DUPLICATE_RECORD",
    }
)


def needs_review(
    cand: ExtractionCandidate,
    result: ValidationResult,
    *,
    is_top100: bool = False,
) -> bool:
    """判定候选是否必须进复核（文档 15）。"""
    # OCR 文本可能存在字符、数字或表格列错位，即使规则校验通过也不能自动发布。
    if "OCR_DERIVED" in cand.flags:
        return True
    if is_top100:
        return True
    if not result.passed:
        return True
    if result.severity == Severity.HIGH:
        return True
    if any(i.code in _REVIEW_TRIGGER_CODES for i in result.issues):
        return True
    return False


def _fact_key(cand: ExtractionCandidate) -> str:
    return make_generation_fact_key(
        entity_id=cand.entity_id,
        period_type=cand.period_type,
        period_label=cand.period_label,
        value_type=cand.value_type,
        measurement_scope=cand.measurement_scope,
    )


def _review_id(entity_id: str, fact_key: str) -> str:
    raw = f"{entity_id}::{FACT_TYPE_GENERATION}::{fact_key}"
    return f"rv_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


class ReviewQueue:
    """复核队列门面：条件判定 → 幂等入队 → 决策记录。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.repo = ReviewRepository(conn)

    def submit(
        self,
        cand: ExtractionCandidate,
        result: ValidationResult,
        *,
        evidence_ids: list[str] | None = None,
        is_top100: bool = False,
        evidence_metadata: dict | None = None,
    ) -> str | None:
        """若需复核则入队，返回 review_id；不需复核返回 None。"""
        if not needs_review(cand, result, is_top100=is_top100):
            return None
        fact_key = _fact_key(cand)
        entity_id = cand.entity_id or ""
        # 同一事实键的同一候选保持幂等；不同 candidate_id 代表冲突版本，
        # 不得覆盖已有复核项，改用候选限定键分别入队。
        existing = self.repo.get_by_fact(entity_id, FACT_TYPE_GENERATION, fact_key)
        conflict = existing is not None and existing["candidate_id"] != cand.candidate_id
        if conflict:
            fact_key = f"{fact_key}::candidate::{cand.candidate_id or 'unknown'}"
        review_id = _review_id(entity_id, fact_key)
        reason = "; ".join(i.code for i in result.issues) or (
            "TOP100_RELATED" if is_top100 else "REVIEW_REQUIRED"
        )
        if conflict:
            reason = f"CONFLICT_CANDIDATE; {reason}"

        # D07: 计算候选哈希（防止旧审批复用）
        if not cand.candidate_id:
            raise ValueError("复核入队前必须先持久化候选")
        candidate_hash = compute_persisted_candidate_hash(
            self.repo.conn,
            cand.candidate_id,
            expected_evidence_ids=evidence_ids,
        )

        payload = json.dumps(
            {
                "candidate": cand.model_dump(mode="json"),
                "validation_issues": [
                    {"code": i.code, "message": i.message, "severity": i.severity}
                    for i in result.issues
                ],
                "evidence_ids": evidence_ids or [],
                "evidence_metadata": evidence_metadata or {},
                "is_top100": is_top100,
                "candidate_hash": candidate_hash,  # D07: 候选内容哈希
            },
            ensure_ascii=False,
            default=str,
        )
        self.repo.enqueue(
            review_id=review_id,
            candidate_id=cand.candidate_id,
            entity_id=entity_id,
            fact_type=FACT_TYPE_GENERATION,
            fact_key=fact_key,
            reason=reason,
            payload=payload,
            task_id=cand.task_id,
        )
        return review_id

    def decide(
        self,
        review_id: str,
        decision: ReviewDecision | str,
        *,
        reviewer: str | None = None,
        resolved_value: str | None = None,
    ) -> None:
        """记录复核决策。"""
        self.repo.resolve(
            review_id,
            decision=str(decision.value if hasattr(decision, "value") else decision),
            reviewer=reviewer,
            resolved_value=resolved_value,
        )

    def is_approved(self, review_id: str) -> bool:
        row = self.repo.get(review_id)
        return row is not None and row["status"] == ReviewDecision.APPROVE.value
