"""Publisher Profile V1：只从已成功的官方来源沉淀机构画像。

这层记忆与电站 Identity Profile 不同：电站画像描述“谁是目标”，发布方画像
描述“哪个经验证机构曾以何种路径发布资料”。它不能接受搜索命中、模型输出或
仅通过 HTTP 探测的 URL，避免让低质量网站获得官方权重。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
from typing import Any
from urllib.parse import urlparse

from ..common.clock import now_iso


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _path_pattern(url: str) -> str | None:
    """将已成功 URL 中的四位年份替换为显式占位符，不猜测其他路径。"""
    path = urlparse(url).path or "/"
    if path == "/":
        return None
    return re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", "{year}", path)


def _json_strings(value: object) -> list[str]:
    try:
        loaded = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in loaded if str(item).strip()))


def _merge_strings(*groups: object, limit: int = 12) -> list[str]:
    result: list[str] = []
    for group in groups:
        values = group if isinstance(group, (list, tuple)) else _json_strings(group)
        for value in values:
            text = str(value).strip()
            if text and text not in result:
                result.append(text)
                if len(result) >= limit:
                    return result
    return result


@dataclass(frozen=True)
class PublisherProfile:
    publisher_profile_id: str
    canonical_name: str
    country: str | None
    publisher_type: str
    official_domain: str
    language: str | None
    report_path_patterns: tuple[str, ...]
    search_patterns: tuple[str, ...]
    reliability_score: float
    success_count: int
    last_success_at: str | None
    verification_basis: str

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> "PublisherProfile":
        value = dict(row)
        return cls(
            publisher_profile_id=str(value["publisher_profile_id"]),
            canonical_name=str(value["canonical_name"]),
            country=str(value.get("country") or "").strip() or None,
            publisher_type=str(value["publisher_type"]),
            official_domain=str(value["official_domain"]),
            language=str(value.get("language") or "").strip() or None,
            report_path_patterns=tuple(_json_strings(value.get("report_path_patterns_json"))),
            search_patterns=tuple(_json_strings(value.get("search_patterns_json"))),
            reliability_score=float(value.get("reliability_score") or 0.0),
            success_count=int(value.get("success_count") or 0),
            last_success_at=str(value.get("last_success_at") or "").strip() or None,
            verification_basis=str(value.get("verification_basis") or ""),
        )

    def to_context(self) -> dict[str, Any]:
        return {
            "publisher_profile_id": self.publisher_profile_id,
            "canonical_name": self.canonical_name,
            "country": self.country,
            "publisher_type": self.publisher_type,
            "official_domain": self.official_domain,
            "language": self.language,
            "report_path_patterns": list(self.report_path_patterns),
            "search_patterns": list(self.search_patterns),
            "reliability_score": self.reliability_score,
            "success_count": self.success_count,
            "last_success_at": self.last_success_at,
            "verification_basis": self.verification_basis,
        }


class PublisherProfileRepository:
    """画像持久层；只由来源成功事件调用，不参与候选准入判定。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def is_available(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publisher_profiles'"
        ).fetchone() is not None

    def profiles_for_entity(self, entity_id: str) -> list[PublisherProfile]:
        if not self.is_available(self.conn):
            return []
        rows = self.conn.execute(
            """SELECT DISTINCT p.*
               FROM publisher_profiles p
               JOIN publisher_profile_observations o
                 ON o.publisher_profile_id=p.publisher_profile_id
               WHERE o.entity_id=?
               ORDER BY p.reliability_score DESC, p.last_success_at DESC, p.canonical_name""",
            (entity_id,),
        ).fetchall()
        return [PublisherProfile.from_row(row) for row in rows]

    def record_success(self, source_id: str) -> PublisherProfile | None:
        """用一条已成功 official 来源更新画像和观察链路。

        调用方须已把来源的 ``success_count``、``last_success`` 更新成功。本方法
        不会改变 sources 的状态或分数；在旧数据库上静默跳过，使版本升级前的
        历史入口保持可用。
        """
        if not self.is_available(self.conn):
            return None
        row = self.conn.execute(
            """SELECT s.source_id, s.entity_id, s.url, s.source_url, s.canonical_url,
                      s.publisher, s.language, s.source_reliability_score,
                      s.success_count, s.last_success, s.source_type, st.country
               FROM sources s
               LEFT JOIN stations st ON st.entity_id=s.entity_id
               WHERE s.source_id=? AND s.source_type='official' AND s.success_count > 0""",
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        source = dict(row)
        url = next((str(source.get(key) or "").strip() for key in ("canonical_url", "source_url", "url")
                    if str(source.get(key) or "").strip()), "")
        domain = _domain(url)
        entity_id = str(source.get("entity_id") or "").strip()
        if not domain or not entity_id:
            return None
        # 用空字符串而非 NULL 作为“未知国家”键，SQLite 的 UNIQUE 会允许多条
        # NULL，导致同一官方域名无法幂等归并。
        country = str(source.get("country") or "").strip()
        profile_id = "publisher_" + hashlib.sha256(
            f"{domain}\x1f{country.lower()}".encode("utf-8")
        ).hexdigest()[:20]
        existing = self.conn.execute(
            "SELECT * FROM publisher_profiles WHERE official_domain=? AND country=?",
            (domain, country),
        ).fetchone()
        existing_value = dict(existing) if existing else {}
        observed_name = str(source.get("publisher") or "").strip() or domain
        canonical_name = str(existing_value.get("canonical_name") or observed_name)
        report_path = _path_pattern(url)
        report_paths = _merge_strings(existing_value.get("report_path_patterns_json"), [report_path] if report_path else [])
        search_patterns = _merge_strings(
            existing_value.get("search_patterns_json"),
            [f"site:{domain} {canonical_name} {{year}} annual report"],
        )
        previous_success = int(existing_value.get("success_count") or 0)
        source_success = int(source.get("success_count") or 0)
        observed_at = str(source.get("last_success") or now_iso())
        reliability = max(
            float(existing_value.get("reliability_score") or 0.0),
            max(0.0, min(1.0, float(source.get("source_reliability_score") or 0.5))),
        )
        now = now_iso()
        self.conn.execute(
            """INSERT INTO publisher_profiles(
                   publisher_profile_id, canonical_name, country, publisher_type,
                   official_domain, language, report_path_patterns_json,
                   search_patterns_json, reliability_score, success_count,
                   last_success_at, verification_basis, created_at, updated_at
               ) VALUES (?, ?, ?, 'official_publisher', ?, ?, ?, ?, ?, ?, ?,
                         'successful_official_source', ?, ?)
               ON CONFLICT(official_domain, country) DO UPDATE SET
                   canonical_name=excluded.canonical_name,
                   language=COALESCE(excluded.language, publisher_profiles.language),
                   report_path_patterns_json=excluded.report_path_patterns_json,
                   search_patterns_json=excluded.search_patterns_json,
                   reliability_score=MAX(publisher_profiles.reliability_score, excluded.reliability_score),
                   success_count=MAX(publisher_profiles.success_count, excluded.success_count),
                   last_success_at=MAX(publisher_profiles.last_success_at, excluded.last_success_at),
                   updated_at=excluded.updated_at""",
            (
                profile_id, canonical_name, country, domain,
                str(source.get("language") or "").strip() or None,
                json.dumps(report_paths, ensure_ascii=False), json.dumps(search_patterns, ensure_ascii=False),
                reliability, max(previous_success, source_success), observed_at, now, now,
            ),
        )
        profile_row = self.conn.execute(
            "SELECT * FROM publisher_profiles WHERE official_domain=? AND country=?",
            (domain, country),
        ).fetchone()
        assert profile_row is not None
        profile = PublisherProfile.from_row(profile_row)
        self.conn.execute(
            """INSERT INTO publisher_profile_observations(
                   publisher_profile_id, source_id, entity_id, observed_url, observed_at
               ) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(publisher_profile_id, source_id) DO UPDATE SET
                   observed_url=excluded.observed_url, observed_at=excluded.observed_at""",
            (profile.publisher_profile_id, source_id, entity_id, url, observed_at),
        )
        return profile
