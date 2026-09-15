"""从已预检 HTML 入口页找出真正可采集的证据文档。

搜索结果常指向新闻或报告索引页，而数值位于 PDF、Excel、CSV 或下载附件中。
本模块只消费 ``UrlProbe`` 已取得的受限链接元数据：不下载附件、不执行深度爬
取、不创建任务或正式文档。附件仍要重新经过 URL 预检和任务相关性校验。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse


_DOCUMENT_SUFFIXES = {
    ".pdf": "pdf", ".xlsx": "excel", ".xls": "excel", ".csv": "csv",
    ".json": "json", ".xml": "xml",
}
_DOCUMENT_TERMS = (
    "download", "attachment", "report", "annual", "generation", "production",
    "statement", "disclosure", "公告", "附件", "下载", "报告", "年报", "发电量",
)


class EvidenceDocumentResolver:
    """有界地把入口页公开附件扩展为候选证据文档。"""

    def __init__(self, *, max_links_per_page: int = 8, max_total_documents: int = 20) -> None:
        self.max_links_per_page = max(1, max_links_per_page)
        self.max_total_documents = max(1, max_total_documents)

    @staticmethod
    def _document_kind(url: str) -> str:
        path = urlparse(url).path.lower()
        for suffix, kind in _DOCUMENT_SUFFIXES.items():
            if path.endswith(suffix):
                return kind
        return "html"

    @staticmethod
    def _normalise_link(value: object) -> tuple[str, str]:
        if isinstance(value, dict):
            return str(value.get("url") or "").strip(), str(value.get("text") or "").strip()
        return str(value or "").strip(), ""

    def _eligible_link(self, url: str, text: str, *, target_period: str, metric: str) -> bool:
        if not url.startswith(("https://", "http://")):
            return False
        kind = self._document_kind(url)
        corpus = f"{url} {text}".lower()
        has_document_signal = kind != "html" or any(term in corpus for term in _DOCUMENT_TERMS)
        if not has_document_signal:
            return False
        # 年份必须能从附件 URL/文字、或由明确的下载类文案推断为“值得二次预检”。
        # 后续 relevance 仍要求站名、年份和全年口径，故这不是放宽正式准入。
        if target_period in corpus:
            return True
        return kind != "html" and any(term in corpus for term in _DOCUMENT_TERMS)

    def expand(
        self,
        candidates: Iterable[dict[str, Any]],
        *,
        target_period: str,
        metric: str,
    ) -> list[dict[str, Any]]:
        """从 ``metadata.discovered_links`` 生成附件候选，保留父页面链路。"""
        parents = list(candidates)
        expanded: list[dict[str, Any]] = []
        seen: set[str] = {
            str(item.get("canonical_url") or item.get("final_url") or item.get("url") or "")
            .rstrip("/").lower()
            for item in parents
        }
        for parent in parents:
            if len(expanded) >= self.max_total_documents:
                break
            metadata = dict(parent.get("metadata") or {})
            raw_links = metadata.get("discovered_links")
            if not isinstance(raw_links, list):
                continue
            parent_url = str(parent.get("final_url") or parent.get("canonical_url") or parent.get("url") or "")
            count = 0
            for raw_link in raw_links:
                if count >= self.max_links_per_page or len(expanded) >= self.max_total_documents:
                    break
                url, text = self._normalise_link(raw_link)
                key = url.rstrip("/").lower()
                if not url or key in seen or not self._eligible_link(
                    url, text, target_period=target_period, metric=metric,
                ):
                    continue
                seen.add(key)
                count += 1
                kind = self._document_kind(url)
                expanded.append({
                    "url": url,
                    "canonical_url": url,
                    "link_text": text or url,
                    "section_title": str(parent.get("link_text") or parent.get("section_title") or parent_url)[:300],
                    "source_type": parent.get("source_type") or "reference",
                    "document_type": kind,
                    "discovery_method": "html_attachment_link",
                    "match_reason": "由已预检入口页的公开附件/下载链接发现；附件将单独验证",
                    "metadata": {
                        "parent_url": parent_url,
                        "parent_title": str(parent.get("link_text") or parent.get("section_title") or "")[:500],
                        "attachment_link_text": text[:500],
                        "discovery_depth": 1,
                        "discovered_from": "html_attachment_link",
                        # 父页文本只作为发现上下文；最终采集、归档、解析仍针对
                        # attachment URL 本身，不能将父页文字当作附件证据。
                        "parent_content_preview": str(metadata.get("content_preview") or "")[:12000],
                    },
                })
        return expanded
