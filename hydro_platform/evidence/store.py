"""证据保存（文档 14）。

从 ExtractionCandidate + 归档文档元数据构造 Evidence，并幂等落库。
证据 id 由事实键 + content_hash 派生：同一事实钉在同一份原始资料上只存一条。
"""

from __future__ import annotations

import sqlite3
import re

from ..database.repositories import EvidenceRepository
from ..models.candidate import ExtractionCandidate
from ..models.evidence import (
    FACT_TYPE_GENERATION,
    Evidence,
    make_generation_fact_key,
)


_PAGE_LOCATOR_RE = re.compile(r"(?:^|[.\s])page\[(\d+)\](?:\.|$)", re.IGNORECASE)
_TABLE_LOCATOR_RE = re.compile(
    r"table\[\d+\](?:\.row\[\d+\])?(?:\.col\[\d+\])?",
    re.IGNORECASE,
)


def _infer_locator_metadata(
    locator: str | None,
    *,
    page_number: int | None,
    table_reference: str | None,
) -> tuple[int | None, str | None]:
    """从结构化 locator 补全可验证的页码/表格坐标。

    抽取器已经把定位写入 ``page[n].ocr`` 或
    ``page[n].table[m].row[r].col[c]``。证据层不应丢掉这类信息，
    但只在格式明确时补全，避免把自然语言片段误判为页码。
    """
    if not locator:
        return page_number, table_reference
    if page_number is None:
        match = _PAGE_LOCATOR_RE.search(locator)
        if match:
            page_number = int(match.group(1))
    if table_reference is None:
        match = _TABLE_LOCATOR_RE.search(locator)
        if match:
            table_reference = match.group(0)
    return page_number, table_reference


def build_evidence_for_candidate(
    cand: ExtractionCandidate,
    *,
    document_id: str | None = None,
    content_hash: str | None = None,
    source_url: str | None = None,
    final_url: str | None = None,
    page_number: int | None = None,
    table_reference: str | None = None,
    section_title: str | None = None,
    parser_version: str | None = None,
) -> Evidence:
    """由候选构造一条证据。定位信息（页码/表格）能拿到多少填多少，绝不编造。"""
    page_number, table_reference = _infer_locator_metadata(
        cand.locator,
        page_number=page_number,
        table_reference=table_reference,
    )
    fact_key = make_generation_fact_key(
        entity_id=cand.entity_id,
        period_type=cand.period_type,
        period_label=cand.period_label,
        value_type=cand.value_type,
        measurement_scope=cand.measurement_scope,
        metric=cand.metric,
    )
    evidence_id = Evidence.derive_id(
        fact_type=FACT_TYPE_GENERATION, fact_key=fact_key, content_hash=content_hash
    )
    return Evidence(
        evidence_id=evidence_id,
        source_id=cand.source_id,
        document_id=document_id,
        content_hash=content_hash,
        fact_type=FACT_TYPE_GENERATION,
        fact_key=fact_key,
        source_url=source_url,
        final_url=final_url,
        page_number=page_number,
        table_reference=table_reference,
        section_title=section_title,
        snippet=cand.snippet,
        locator=cand.locator,
        confidence=cand.confidence,
        parser_version=parser_version,
        extraction_version=cand.extractor,
        task_id=cand.task_id,
    )


class EvidenceStore:
    """证据落库门面：构造 + 幂等写入，返回 evidence_id。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.repo = EvidenceRepository(conn)

    def save_for_candidate(self, cand: ExtractionCandidate, **meta) -> str:
        """为候选保存证据，返回 evidence_id（已存在则复用同一 id）。"""
        ev = build_evidence_for_candidate(cand, **meta)
        self.repo.insert_if_absent(ev)
        return ev.evidence_id
