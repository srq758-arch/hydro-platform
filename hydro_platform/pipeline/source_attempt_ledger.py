"""CandidateSource / SourceAttempt 的短事务持久化。

网络、浏览器和解析工作不得在 SQLite 写事务中运行。每个方法只做一次很短的
状态写入并立即提交，使失败诊断可恢复，同时降低 database is locked 风险。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from ..common.clock import now_iso
from ..common.enums import (
    AccessMethod,
    CandidateSourceStatus,
    SourceAttemptStatus,
)
from ..models.source_pipeline import CandidateSource, SourceAttempt


class SourceAttemptLedger:
    """保存统一来源及其独立尝试状态。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def is_available(conn: sqlite3.Connection) -> bool:
        """正式库尚未升级 v13 时允许旧程序继续启动，但不伪造台账。"""
        required = {"candidate_sources", "source_attempts"}
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
            tuple(required),
        ).fetchall()
        return {row[0] for row in rows} == required

    def record_candidate(self, source: CandidateSource) -> None:
        lead_id = source.lead_id
        if lead_id:
            exists = self.conn.execute(
                "SELECT 1 FROM search_leads WHERE lead_id=?", (lead_id,)
            ).fetchone()
            if not exists:
                # SearchLead 的持久化将在搜索 provider 适配时完成。不能为满足
                # 外键伪造原始搜索内容；暂以 direct lineage 保存候选。
                lead_id = None
        self.conn.execute(
            """INSERT INTO candidate_sources(
                   candidate_source_id, task_id, lead_id, url, canonical_url,
                   title, publisher, source_type, discovery_method,
                   expected_content_kind, language, priority_score, status,
                   metadata_json, lineage_hash, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(candidate_source_id) DO UPDATE SET
                   priority_score=excluded.priority_score,
                   status=excluded.status,
                   metadata_json=excluded.metadata_json""",
            (
                source.candidate_source_id, source.task_id, lead_id, source.url,
                source.canonical_url, source.title, source.publisher, source.source_type,
                source.discovery_method, source.expected_content_kind.value, source.language,
                source.priority_score, source.status.value,
                json.dumps(source.metadata, ensure_ascii=False, sort_keys=True),
                source.lineage_hash, source.created_at,
            ),
        )
        self.conn.commit()

    def start_attempt(
        self,
        source: CandidateSource,
        access_method: AccessMethod | None = None,
    ) -> SourceAttempt:
        self.record_candidate(source)
        row = self.conn.execute(
            """SELECT COALESCE(MAX(attempt_no), 0) + 1
               FROM source_attempts WHERE candidate_source_id=?""",
            (source.candidate_source_id,),
        ).fetchone()
        attempt = SourceAttempt(
            task_id=source.task_id,
            candidate_source_id=source.candidate_source_id,
            attempt_no=int(row[0]),
            access_method=access_method,
            status=SourceAttemptStatus.RUNNING,
            started_at=now_iso(),
        )
        self.conn.execute(
            """INSERT INTO source_attempts(
                   attempt_id, task_id, candidate_source_id, attempt_no,
                   access_method, status, started_at, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt.attempt_id, attempt.task_id, attempt.candidate_source_id,
                attempt.attempt_no,
                attempt.access_method.value if attempt.access_method else None,
                attempt.status.value, attempt.started_at, attempt.created_at,
            ),
        )
        self.conn.execute(
            "UPDATE candidate_sources SET status=? WHERE candidate_source_id=?",
            (CandidateSourceStatus.QUEUED.value, attempt.candidate_source_id),
        )
        self.conn.commit()
        return attempt

    def fail(
        self,
        attempt: SourceAttempt,
        *,
        failure_stage: str,
        failure_code: str,
        error: str,
    ) -> None:
        self.conn.execute(
            """UPDATE source_attempts
               SET status=?, failure_stage=?, failure_code=?, error=?, finished_at=?
               WHERE attempt_id=? AND status=?""",
            (
                SourceAttemptStatus.FAILED.value, failure_stage, failure_code,
                error[:2000], now_iso(), attempt.attempt_id,
                SourceAttemptStatus.RUNNING.value,
            ),
        )
        self.conn.execute(
            "UPDATE candidate_sources SET status=? WHERE candidate_source_id=?",
            (CandidateSourceStatus.EXHAUSTED.value, attempt.candidate_source_id),
        )
        self.conn.commit()

    def cancel(self, attempt: SourceAttempt, *, reason: str) -> None:
        """只允许 running→cancelled；终态 attempt 不被覆盖。"""
        self.conn.execute(
            """UPDATE source_attempts
               SET status=?, failure_stage='CANCELLED', failure_code='CANCELLED',
                   error=?, finished_at=?
               WHERE attempt_id=? AND status=?""",
            (
                SourceAttemptStatus.CANCELLED.value, reason[:2000], now_iso(),
                attempt.attempt_id, SourceAttemptStatus.RUNNING.value,
            ),
        )
        self.conn.execute(
            "UPDATE candidate_sources SET status=? WHERE candidate_source_id=?",
            (CandidateSourceStatus.CANCELLED.value, attempt.candidate_source_id),
        )
        self.conn.commit()

    def attach_document(self, attempt: SourceAttempt, *, document_id: str, content_hash: str) -> None:
        """绑定已归档文档但保持 running，解析/抽取仍可能失败。"""
        lineage_hash = hashlib.sha256(
            f"{attempt.attempt_id}::{document_id}::{content_hash}".encode()
        ).hexdigest()
        self.conn.execute(
            """UPDATE source_attempts
               SET document_id=?
               WHERE attempt_id=? AND status=?""",
            (
                document_id, attempt.attempt_id, SourceAttemptStatus.RUNNING.value,
            ),
        )
        self.conn.execute(
            """UPDATE documents SET source_attempt_id=?, lineage_hash=?
               WHERE document_id=?""",
            (attempt.attempt_id, lineage_hash, document_id),
        )
        self.conn.commit()

    def succeed(self, attempt: SourceAttempt, *, document_id: str, content_hash: str) -> None:
        self.attach_document(attempt, document_id=document_id, content_hash=content_hash)
        self.conn.execute(
            """UPDATE source_attempts SET status=?, finished_at=?
               WHERE attempt_id=? AND status=?""",
            (
                SourceAttemptStatus.SUCCEEDED.value, now_iso(), attempt.attempt_id,
                SourceAttemptStatus.RUNNING.value,
            ),
        )
        self.conn.execute(
            "UPDATE candidate_sources SET status=? WHERE candidate_source_id=?",
            (CandidateSourceStatus.SUCCEEDED.value, attempt.candidate_source_id),
        )
        self.conn.commit()

    def bind_candidate(
        self,
        attempt: SourceAttempt,
        *,
        document_id: str,
        candidate_id: str,
        payload: dict,
        extractor_version: str,
    ) -> str:
        """把已持久化候选绑定到具体 attempt，返回候选 lineage hash。"""
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        lineage_hash = hashlib.sha256(
            (
                f"{attempt.attempt_id}::{document_id}::{candidate_id}::"
                f"{payload_hash}::{extractor_version}"
            ).encode()
        ).hexdigest()
        cursor = self.conn.execute(
            """UPDATE extraction_candidates
               SET source_attempt_id=?, lineage_hash=?
               WHERE candidate_id=? AND document_id=?""",
            (attempt.attempt_id, lineage_hash, candidate_id, document_id),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise RuntimeError(f"候选 lineage 绑定失败: {candidate_id}")
        self.conn.commit()
        return lineage_hash
