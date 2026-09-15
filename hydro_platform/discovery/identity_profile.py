"""Seedlist 驱动的电站身份画像与可审计查询词生成。"""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Any, Iterable
from urllib.parse import urlparse


def _unique(values: Iterable[object]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _split_aliases(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return _unique(re.split(r"[;,|/；、\n]", value))
    if isinstance(value, Iterable):
        return _unique(value)
    return ()


@dataclass(frozen=True)
class StationIdentityProfile:
    """不可变身份视图；不会自动覆盖 seedlist 核心字段。"""

    entity_id: str
    canonical_name: str
    local_name: str | None
    aliases: tuple[str, ...]
    country: str | None
    region: str | None
    river: str | None
    capacity_mw: float | None
    operator: str | None
    owner: str | None
    official_domains: tuple[str, ...] = ()
    official_entry_urls: tuple[str, ...] = ()
    publisher_profiles: tuple[dict[str, Any], ...] = ()

    @property
    def search_names(self) -> tuple[str, ...]:
        """优先当地名和明确别名，避免用非常长的英文 seed 名称独占查询预算。"""
        return _unique((self.local_name, *self.aliases, self.canonical_name))

    def station_context(self) -> dict[str, Any]:
        """给相关性校验和模型规划的只读上下文。"""
        return {
            "entity_id": self.entity_id,
            "canonical_name": self.canonical_name,
            "local_name": self.local_name,
            "aliases": list(self.aliases),
            "search_aliases": list(self.search_names),
            "country": self.country,
            "region": self.region,
            "river": self.river,
            "capacity_mw": self.capacity_mw,
            "operator": self.operator,
            "owner": self.owner,
            "official_domains": list(self.official_domains),
            # 仅来自历史成功/人工接受的官方来源；给受控站内探索作为入口，
            # 不能由普通搜索结果、GEM 外链或模型输出填充。
            "official_entry_urls": list(self.official_entry_urls),
            "publisher_profiles": [dict(item) for item in self.publisher_profiles],
        }


def _domains_from_rows(rows: Iterable[sqlite3.Row | dict[str, Any]]) -> tuple[str, ...]:
    domains: list[str] = []
    for row in rows:
        value = dict(row)
        for key in ("canonical_url", "source_url", "url", "candidate_url", "final_url"):
            url = str(value.get(key) or "").strip()
            domain = urlparse(url).netloc.lower().removeprefix("www.")
            if domain and domain not in domains:
                domains.append(domain)
    return tuple(domains)


def _entry_urls_from_rows(rows: Iterable[sqlite3.Row | dict[str, Any]]) -> tuple[str, ...]:
    """提取已经验证的 HTTP 入口，保持来源表给出的优先级。"""
    urls: list[str] = []
    for row in rows:
        value = dict(row)
        for key in ("canonical_url", "source_url", "url", "candidate_url", "final_url"):
            url = str(value.get(key) or "").strip()
            if urlparse(url).scheme in {"http", "https"} and url not in urls:
                urls.append(url)
    return tuple(urls)


def build_station_identity_profile(conn: sqlite3.Connection, station: dict[str, Any]) -> StationIdentityProfile:
    """从 seedlist 行及已人工接受/历史成功来源构造画像。

    未核实的搜索候选不能被升级为官方域名。只有历史成功来源或人工接受的
    ``source_discoveries`` 才能贡献 ``site:`` 定向查询域名。
    """
    entity_id = str(station.get("entity_id") or "").strip()
    domains: list[str] = []
    entry_urls: list[str] = []
    try:
        source_rows = conn.execute(
            """SELECT source_url, canonical_url, url FROM sources
               WHERE entity_id=? AND source_type='official' AND success_count > 0
               ORDER BY last_success DESC LIMIT 8""",
            (entity_id,),
        ).fetchall()
        domains.extend(_domains_from_rows(source_rows))
        entry_urls.extend(_entry_urls_from_rows(source_rows))
    except sqlite3.OperationalError:
        # 最小/旧 schema 可以没有来源画像列；仍可仅用 seedlist 搜索。
        pass
    try:
        discovery_rows = conn.execute(
            """SELECT candidate_url, canonical_url, final_url FROM source_discoveries
               WHERE entity_id=? AND source_type='official' AND status='accepted'
               ORDER BY updated_at DESC LIMIT 8""",
            (entity_id,),
        ).fetchall()
        domains.extend(_domains_from_rows(discovery_rows))
        entry_urls.extend(_entry_urls_from_rows(discovery_rows))
    except sqlite3.OperationalError:
        pass
    publisher_profiles: tuple[dict[str, Any], ...] = ()
    try:
        from .publisher_profile import PublisherProfileRepository
        publisher_profiles = tuple(
            profile.to_context()
            for profile in PublisherProfileRepository(conn).profiles_for_entity(entity_id)
        )
    except sqlite3.OperationalError:
        # v15 尚未应用的只读/旧数据库仍可使用身份画像和搜索，不触发写迁移。
        pass
    return StationIdentityProfile(
        entity_id=entity_id,
        canonical_name=str(station.get("canonical_name") or entity_id),
        local_name=str(station.get("local_name") or "").strip() or None,
        aliases=_split_aliases(station.get("aliases")),
        country=str(station.get("country") or "").strip() or None,
        region=str(station.get("region") or "").strip() or None,
        river=str(station.get("river") or "").strip() or None,
        capacity_mw=station.get("capacity_mw"),
        operator=str(station.get("operator") or "").strip() or None,
        owner=str(station.get("owner") or "").strip() or None,
        official_domains=_unique(domains),
        official_entry_urls=_unique(entry_urls),
        publisher_profiles=publisher_profiles,
    )
