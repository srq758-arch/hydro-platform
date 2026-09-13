"""证据模型（文档 14）。

Evidence 把一条候选事实钉回到具体原始资料/页面/表格位置，且与原始资料
（document_id + content_hash）不可脱钩。evidence_id 由内容派生，保证幂等。
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict

FACT_TYPE_GENERATION = "generation"


def make_generation_fact_key(
    *,
    entity_id: str | None,
    period_type: str | None,
    period_label: str | None,
    value_type: str | None,
    measurement_scope: str | None,
) -> str:
    """与 generation_records 唯一键一致的事实键，用于证据/复核去重。"""
    parts = [
        entity_id or "",
        str(period_type or ""),
        period_label or "",
        str(value_type or ""),
        str(measurement_scope or ""),
    ]
    return "|".join(parts)


class Evidence(BaseModel):
    """一条证据。多数字段可空——能拿到多少就记多少，绝不编造定位信息。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    evidence_id: str
    source_id: str | None = None
    document_id: str | None = None
    content_hash: str | None = None
    fact_type: str = FACT_TYPE_GENERATION
    fact_key: str = ""
    source_url: str | None = None
    final_url: str | None = None
    page_number: int | None = None
    table_reference: str | None = None
    section_title: str | None = None
    snippet: str | None = None
    locator: str | None = None
    confidence: float | None = None
    parser_version: str | None = None
    extraction_version: str | None = None
    task_id: str | None = None
    created_at: str | None = None

    @staticmethod
    def derive_id(*, fact_type: str, fact_key: str, content_hash: str | None) -> str:
        """由 fact_type+fact_key+content_hash 派生 evidence_id：同事实同来源 → 同 id。"""
        raw = f"{fact_type}::{fact_key}::{content_hash or ''}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        return f"ev_{digest}"
