"""搜索结果聚合与来源地址归一化。

聚合层只处理候选和访问预检结果，不下载、解析或写入正式事实。它保留首个
原始 URL，并把重定向地址、大小写/端口/追踪参数变体记录为别名，避免同一份
证据在多个搜索引擎中重复占用预算，同时不误删下载签名和业务查询参数。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class SearchAggregator:
    """对候选执行保守规范化、去重和发布方元数据补充。"""

    _TRACKING_QUERY_KEYS = frozenset({
        "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "referrer",
        "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term",
    })

    @classmethod
    def canonicalize_url(cls, value: str) -> str:
        """生成用于去重/谱系的规范 URL，不改变用户看到的原始 URL。"""
        raw = str(value or "").strip()
        if not raw:
            return raw
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return raw.rstrip("/")
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return raw.rstrip("/")
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return raw.rstrip("/")
        try:
            port = parsed.port
        except ValueError:
            return raw
        netloc = hostname
        if port is not None and not (
            (parsed.scheme.lower() == "https" and port == 443)
            or (parsed.scheme.lower() == "http" and port == 80)
        ):
            netloc = f"{netloc}:{port}"
        path = parsed.path or "/"
        while "//" in path:
            path = path.replace("//", "/")
        if path != "/":
            path = path.rstrip("/")
        query = urlencode(
            [
                (key, item)
                for key, item in parse_qsl(parsed.query, keep_blank_values=True)
                if key.lower() not in cls._TRACKING_QUERY_KEYS
            ],
            doseq=True,
        )
        return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))

    @classmethod
    def publisher_domain(cls, value: str) -> str:
        """返回用于发布方聚合的注册主机（只去掉 www 前缀）。"""
        parsed = urlsplit(cls.canonicalize_url(value))
        return parsed.netloc.lower().removeprefix("www.")

    @classmethod
    def merge(
        cls,
        candidates: Iterable[dict[str, Any]],
        *,
        prefer_final: bool = False,
    ) -> list[dict[str, Any]]:
        """按规范地址合并候选，保留顺序和所有可审计 URL 别名。

        ``prefer_final=True`` 仅用于 UrlProbe 之后：若 HTTP 发生重定向，则以
        最终地址作为规范地址，原始入口写入 ``metadata.alias_urls``。第一条
        候选的业务字段和排名保持不变，后续重复项只补充别名/发布方元数据。
        """
        merged: list[dict[str, Any]] = []
        index: dict[str, int] = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            original_url = str(candidate.get("url") or "").strip()
            final_url = str(candidate.get("final_url") or "").strip()
            source_url = final_url if prefer_final and final_url.startswith(("http://", "https://")) else (
                str(candidate.get("canonical_url") or original_url).strip()
            )
            canonical = cls.canonicalize_url(source_url)
            if not canonical:
                continue
            metadata = dict(candidate.get("metadata") or {})
            aliases = list(metadata.get("alias_urls") or [])
            for alias in (original_url, str(candidate.get("canonical_url") or "").strip(), final_url):
                if alias and alias not in aliases and cls.canonicalize_url(alias) != canonical:
                    aliases.append(alias)
            if aliases:
                metadata["alias_urls"] = aliases[:20]
            metadata.setdefault("publisher_domain", cls.publisher_domain(canonical))
            metadata.setdefault("discovery_depth", 0)
            enriched = {**candidate, "canonical_url": canonical, "metadata": metadata}
            existing_index = index.get(canonical)
            if existing_index is None:
                index[canonical] = len(merged)
                merged.append(enriched)
                continue
            existing = merged[existing_index]
            existing_metadata = dict(existing.get("metadata") or {})
            existing_aliases = list(existing_metadata.get("alias_urls") or [])
            for alias in aliases:
                if alias not in existing_aliases:
                    existing_aliases.append(alias)
            if existing_aliases:
                existing_metadata["alias_urls"] = existing_aliases[:20]
            if not existing_metadata.get("publisher_domain"):
                existing_metadata["publisher_domain"] = metadata.get("publisher_domain")
            existing["metadata"] = existing_metadata
        return merged

    @classmethod
    def publisher_summary(cls, candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """生成只含聚合统计的发布方摘要，不包含正文或密钥。"""
        grouped: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            url = str(candidate.get("canonical_url") or candidate.get("final_url") or candidate.get("url") or "")
            domain = cls.publisher_domain(url)
            if not domain:
                continue
            item = grouped.setdefault(domain, {"publisher_domain": domain, "count": 0, "source_types": set()})
            item["count"] = int(item["count"]) + 1
            source_type = str(candidate.get("source_type") or "unknown")
            item["source_types"].add(source_type)
        return [
            {**item, "source_types": sorted(item["source_types"])}
            for item in sorted(grouped.values(), key=lambda value: (-int(value["count"]), value["publisher_domain"]))
        ]
