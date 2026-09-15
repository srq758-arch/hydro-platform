"""B0 统一来源管线契约。

五层对象严格区分“搜索线索、可尝试来源、一次获取尝试、归档证据文档、
从证据产生的候选”。对象只表达数据与 lineage，不执行网络或数据库操作。
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..common.clock import now_iso
from ..common.enums import (
    AccessMethod,
    CandidateSourceStatus,
    ContentKind,
    EvidenceCandidateStatus,
    SearchLeadStatus,
    SourceAttemptStatus,
)


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join("" if part is None else str(part).strip() for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} 不能为空")
    return value


class SearchLead(BaseModel):
    """搜索工具返回的原始线索；尚未承诺可访问或适合作为证据。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    lead_id: str | None = None
    task_id: str
    provider: str
    query: str
    url: str
    title: str | None = None
    snippet: str | None = None
    rank: int | None = Field(default=None, ge=1)
    raw_payload_hash: str | None = None
    status: SearchLeadStatus = SearchLeadStatus.DISCOVERED
    discovered_at: str = Field(default_factory=now_iso)

    @field_validator("task_id", "provider", "query", "url")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _derive_id(self) -> "SearchLead":
        if self.lead_id is None:
            self.lead_id = _stable_id(
                "lead", self.task_id, self.provider, self.query, self.url, self.rank
            )
        return self


class CandidateSource(BaseModel):
    """已归一化、可排序并可交给采集队列尝试的来源。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    candidate_source_id: str | None = None
    task_id: str
    lead_id: str | None = None
    url: str
    canonical_url: str
    title: str | None = None
    publisher: str | None = None
    source_type: str = "unknown"
    discovery_method: str
    expected_content_kind: ContentKind = ContentKind.ANY
    language: str | None = None
    priority_score: float = Field(default=0.0, ge=0.0, le=1.0)
    status: CandidateSourceStatus = CandidateSourceStatus.ELIGIBLE
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    lineage_hash: str | None = None

    @field_validator("task_id", "url", "canonical_url", "discovery_method")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _derive_lineage(self) -> "CandidateSource":
        if self.candidate_source_id is None:
            self.candidate_source_id = _stable_id(
                "src", self.task_id, self.lead_id, self.canonical_url
            )
        if self.lineage_hash is None:
            self.lineage_hash = hashlib.sha256(
                f"{self.lead_id or 'direct'}::{self.canonical_url}::{self.discovery_method}".encode()
            ).hexdigest()
        return self

    @property
    def expected(self) -> ContentKind:
        """短期兼容旧 Acquisition 调用；新代码使用 expected_content_kind。"""
        return self.expected_content_kind


class SourceAttempt(BaseModel):
    """针对一个 CandidateSource 的一次获取尝试。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    attempt_id: str | None = None
    task_id: str
    candidate_source_id: str
    attempt_no: int = Field(ge=1)
    access_method: AccessMethod | None = None
    status: SourceAttemptStatus = SourceAttemptStatus.PENDING
    failure_stage: str | None = None
    failure_code: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    document_id: str | None = None
    created_at: str = Field(default_factory=now_iso)

    @field_validator("task_id", "candidate_source_id")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_result(self) -> "SourceAttempt":
        if self.attempt_id is None:
            self.attempt_id = _stable_id(
                "attempt", self.task_id, self.candidate_source_id, self.attempt_no
            )
        if self.status == SourceAttemptStatus.SUCCEEDED and not self.document_id:
            raise ValueError("成功的 SourceAttempt 必须关联 document_id")
        if self.status == SourceAttemptStatus.FAILED and not (self.failure_code or self.error):
            raise ValueError("失败的 SourceAttempt 必须提供 failure_code 或 error")
        return self


class EvidenceDocument(BaseModel):
    """由一次成功 SourceAttempt 产生的不可变归档文档。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str
    source_attempt_id: str
    task_id: str
    original_url: str
    final_url: str
    content_hash: str
    file_size: int = Field(ge=0)
    content_kind: ContentKind
    local_path: str
    archived_at: str = Field(default_factory=now_iso)
    lineage_hash: str | None = None

    @field_validator(
        "document_id", "source_attempt_id", "task_id", "original_url", "final_url", "local_path"
    )
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("content_hash")
    @classmethod
    def _sha256(cls, value: str) -> str:
        value = value.lower()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("content_hash 必须是 64 位 SHA256")
        return value

    @model_validator(mode="after")
    def _derive_lineage(self) -> "EvidenceDocument":
        if self.lineage_hash is None:
            self.lineage_hash = hashlib.sha256(
                f"{self.source_attempt_id}::{self.document_id}::{self.content_hash}".encode()
            ).hexdigest()
        return self


class EvidenceCandidate(BaseModel):
    """从 EvidenceDocument 抽取出的通用事实候选 lineage。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    candidate_id: str
    source_attempt_id: str
    evidence_document_id: str
    task_id: str
    entity_id: str
    fact_type: str
    fact_key: str
    payload_hash: str
    extractor_version: str
    status: EvidenceCandidateStatus = EvidenceCandidateStatus.EXTRACTED
    created_at: str = Field(default_factory=now_iso)
    lineage_hash: str | None = None

    @field_validator(
        "candidate_id", "source_attempt_id", "evidence_document_id", "task_id",
        "entity_id", "fact_type", "fact_key", "extractor_version"
    )
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("payload_hash")
    @classmethod
    def _payload_sha256(cls, value: str) -> str:
        value = value.lower()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("payload_hash 必须是 64 位 SHA256")
        return value

    @model_validator(mode="after")
    def _derive_lineage(self) -> "EvidenceCandidate":
        if self.lineage_hash is None:
            self.lineage_hash = hashlib.sha256(
                (
                    f"{self.source_attempt_id}::{self.evidence_document_id}::"
                    f"{self.candidate_id}::{self.payload_hash}::{self.extractor_version}"
                ).encode()
            ).hexdigest()
        return self
