"""SearchLead 的短事务审计台账。

搜索结果只是线索，不能直接视为来源或证据。本模块保存每个 provider 的原始
URL、查询词、排名和不可逆 payload hash；后续 CandidateSource 只通过 lead_id
引用这些线索。网络搜索从不在这里执行。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from ..common.enums import SearchLeadStatus
from ..models.source_pipeline import SearchLead


class SearchLeadLedger:
    """在 v13+ 数据库中幂等持久化 provider 原始搜索结果。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def is_available(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_leads'"
        ).fetchone()
        return row is not None

    def record_results(
        self,
        *,
        task_id: str,
        provider: str,
        default_query: str,
        results: Iterable[Mapping[str, Any]],
    ) -> dict[str, str]:
        """保存原始结果，返回 ``canonical_url → lead_id``。

        同一个 task/provider/query/url/rank 的 lead_id 稳定，因此可重复搜索而
        不产生重复行。保留第一条 URL 映射，避免同 URL 的后续镜像结果抢占
        原始 provider lineage。
        """
        if not task_id or not provider:
            raise ValueError("task_id 和 provider 不能为空")
        if not SearchLeadLedger.is_available(self.conn):
            return {}

        lead_by_url: dict[str, str] = {}
        for rank, raw in enumerate(results, start=1):
            url = str(raw.get("canonical_url") or raw.get("final_url") or raw.get("url") or "").strip()
            if not url.startswith(("https://", "http://")):
                continue
            query = str(raw.get("query") or default_query or "provider search").strip()
            raw_json = json.dumps(dict(raw), ensure_ascii=False, sort_keys=True, default=str)
            lead = SearchLead(
                task_id=task_id,
                provider=str(
                    raw.get("search_provider")
                    or raw.get("search_engine")
                    or raw.get("_provider_label")
                    or raw.get("provider")
                    or provider
                ),
                query=query,
                url=url,
                title=str(raw.get("title") or raw.get("link_text") or "")[:500] or None,
                snippet=str(raw.get("snippet") or raw.get("match_reason") or "")[:2000] or None,
                rank=rank,
                raw_payload_hash=hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
                status=SearchLeadStatus.DISCOVERED,
            )
            self.conn.execute(
                """INSERT INTO search_leads(
                       lead_id, task_id, provider, query_text, url, title, snippet,
                       rank, raw_payload_hash, status, discovered_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(lead_id) DO UPDATE SET
                       title=excluded.title, snippet=excluded.snippet,
                       raw_payload_hash=excluded.raw_payload_hash,
                       status=CASE WHEN search_leads.status='rejected'
                                   THEN search_leads.status ELSE excluded.status END""",
                (
                    lead.lead_id, lead.task_id, lead.provider, lead.query, lead.url,
                    lead.title, lead.snippet, lead.rank, lead.raw_payload_hash,
                    lead.status.value, lead.discovered_at,
                ),
            )
            lead_by_url.setdefault(url.rstrip("/").lower(), str(lead.lead_id))
        self.conn.commit()
        return lead_by_url

    def update_status(self, lead_ids: Iterable[str], status: SearchLeadStatus) -> None:
        """只更新本次确实处理过的线索，不猜测未采用重复项的结论。"""
        unique_ids = list(dict.fromkeys(str(lead_id) for lead_id in lead_ids if lead_id))
        if not unique_ids or not SearchLeadLedger.is_available(self.conn):
            return
        self.conn.executemany(
            "UPDATE search_leads SET status=? WHERE lead_id=?",
            [(status.value, lead_id) for lead_id in unique_ids],
        )
        self.conn.commit()
