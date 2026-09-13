"""来源发现台账：发现候选和已验证来源必须保持隔离。"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Iterable

from ..common.clock import now_iso


class SourceDiscoveryLedger:
    """按 ``entity_id + canonical_url`` 幂等保存可审阅的发现候选。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record_candidates(self, *, entity_id: str, gem_wiki_url: str | None, candidates: Iterable[dict]) -> list[dict]:
        now = now_iso()
        stored: list[dict] = []
        for candidate in candidates:
            canonical_url = candidate.get("canonical_url") or candidate["url"]
            existing = self.conn.execute(
                "SELECT discovery_id, status FROM source_discoveries WHERE entity_id = ? AND canonical_url = ?",
                (entity_id, canonical_url),
            ).fetchone()
            discovery_id = existing["discovery_id"] if existing else f"disc_{uuid.uuid4().hex[:16]}"
            # 人工接受/驳回结论不能被重新探测覆盖；普通发现状态可刷新。
            status = existing["status"] if existing and existing["status"] in {"accepted", "rejected"} else candidate.get("status", "discovered")
            self.conn.execute(
                """INSERT INTO source_discoveries (
                       discovery_id, entity_id, gem_wiki_url, candidate_url, canonical_url,
                       link_text, section_title, source_type, document_type, discovery_method,
                       match_reason, estimated_reliability, task_fit_score, combined_score,
                       status, discovered_at, updated_at, access_status, http_status,
                       final_url, checked_at, error
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(entity_id, canonical_url) DO UPDATE SET
                       gem_wiki_url=excluded.gem_wiki_url, candidate_url=excluded.candidate_url,
                       link_text=excluded.link_text, section_title=excluded.section_title,
                       source_type=excluded.source_type, document_type=excluded.document_type,
                       discovery_method=excluded.discovery_method, match_reason=excluded.match_reason,
                       estimated_reliability=excluded.estimated_reliability,
                       task_fit_score=excluded.task_fit_score, combined_score=excluded.combined_score,
                       updated_at=excluded.updated_at, access_status=excluded.access_status,
                       http_status=excluded.http_status, final_url=excluded.final_url,
                       checked_at=excluded.checked_at, error=excluded.error""",
                (discovery_id, entity_id, gem_wiki_url, candidate["url"], canonical_url,
                 candidate.get("link_text"), candidate.get("section_title"),
                 candidate.get("source_type", "reference"), candidate.get("document_type", "html"),
                 candidate.get("discovery_method", "unknown"), candidate.get("match_reason"),
                 candidate.get("estimated_reliability"), candidate.get("task_fit_score"),
                 candidate.get("combined_score"), status, now, now,
                 candidate.get("access_status", "unverified"), candidate.get("http_status"),
                 candidate.get("final_url"), now, candidate.get("error")),
            )
            stored.append({**candidate, "discovery_id": discovery_id, "status": status})
        self.conn.commit()
        return stored

    def list_for_entity(self, entity_id: str, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            """SELECT discovery_id, candidate_url, canonical_url, link_text, section_title,
                      source_type, document_type, discovery_method, match_reason,
                      estimated_reliability, task_fit_score, combined_score, status, access_status,
                      http_status, final_url, checked_at, error, discovered_at, updated_at
               FROM source_discoveries WHERE entity_id = ?
               ORDER BY combined_score DESC, updated_at DESC LIMIT ?""",
            (entity_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
