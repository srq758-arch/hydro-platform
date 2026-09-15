"""受控的已验证官网站内发现。

这不是通用爬虫，也不会从搜索结果推断某个域名“可能是官网”。它只消费
``StationIdentityProfile`` 已给出的、来自历史成功或人工接受来源的官方入口和
域名，在很小的页面预算内查找公开报告索引、下载页和 sitemap 中的证据链接。

发现阶段只产生候选；候选仍要回到 ``UrlProbe`` 与相关性硬校验，之后才能由
人工选择为采集来源。这样不会把站内导航页的存在误当成全年发电量事实。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping
from urllib.parse import urljoin, urlparse
import re

import requests
from bs4 import BeautifulSoup


_DOCUMENT_SUFFIXES = {
    ".pdf": "pdf", ".xlsx": "excel", ".xls": "excel", ".csv": "csv",
    ".json": "json", ".xml": "xml",
}
_DOCUMENT_TERMS = (
    "download", "attachment", "report", "annual", "generation", "production",
    "statement", "disclosure", "investor", "公告", "附件", "下载", "报告", "年报",
    "发电量", "信息披露", "投资者",
)


@dataclass(frozen=True)
class FetchedOfficialPage:
    """受限 HTTP 读取的最小返回值，便于完全离线地测试探索行为。"""

    status_code: int
    content_type: str
    text: str
    final_url: str


class OfficialSiteExplorer:
    """仅在已验证官网范围内有界探索公开资料链接。

    默认最多访问 6 个 HTML/XML 入口，导航深度最多 1。PDF/表格文件只是作为
    候选返回、后续由 ``UrlProbe`` 单独预检，不会在这里下载或归档。
    """

    def __init__(
        self,
        *,
        fetch: Callable[[str], FetchedOfficialPage] | None = None,
        max_pages: int = 6,
        max_depth: int = 1,
        timeout: float = 10.0,
    ) -> None:
        self.max_pages = max(1, min(int(max_pages), 12))
        self.max_depth = max(0, min(int(max_depth), 2))
        self.timeout = timeout
        self._fetch = fetch or self._request

    def _request(self, url: str) -> FetchedOfficialPage:
        response = requests.get(
            url,
            timeout=self.timeout,
            allow_redirects=True,
            headers={"User-Agent": "HydroPlatform/1.0 (+official-site-discovery)"},
        )
        try:
            # 站内导航与 sitemap 都是小文本；限制体积，绝不把本阶段变成下载器。
            body = response.content[:256 * 1024]
            declared = str(response.headers.get("Content-Type") or "")
            encoding = response.encoding or "utf-8"
            return FetchedOfficialPage(
                status_code=int(response.status_code), content_type=declared,
                text=body.decode(encoding, errors="replace"), final_url=response.url or url,
            )
        finally:
            response.close()

    @staticmethod
    def _host(url: str) -> str:
        return urlparse(url).netloc.lower().removeprefix("www.")

    @classmethod
    def _same_official_domain(cls, url: str, domains: set[str]) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and cls._host(url) in domains

    @staticmethod
    def _kind(url: str) -> str:
        path = urlparse(url).path.lower()
        for suffix, kind in _DOCUMENT_SUFFIXES.items():
            if path.endswith(suffix):
                return kind
        return "html"

    @staticmethod
    def _normalise_url(url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(fragment="").geturl()

    @classmethod
    def _is_document_link(cls, url: str, text: str, target_period: str) -> bool:
        corpus = f"{url} {text}".lower()
        kind = cls._kind(url)
        return kind != "html" or (
            target_period in corpus and any(term in corpus for term in _DOCUMENT_TERMS)
        )

    @staticmethod
    def _is_navigation_link(url: str, text: str, target_period: str) -> bool:
        corpus = f"{url} {text}".lower()
        # 只追踪有报告/披露/数据语义的同域入口；年份提高优先级但不是硬条件，
        # 因为许多官网把当前年度报告放在不含年份的 /investor/reports 路径。
        return any(term in corpus for term in _DOCUMENT_TERMS) or target_period in corpus

    @classmethod
    def _candidate(
        cls,
        *,
        url: str,
        text: str,
        parent_url: str,
        depth: int,
        method: str,
        official_domain: str,
    ) -> dict[str, object]:
        return {
            "url": url,
            "canonical_url": url,
            "link_text": text[:500] or url,
            "section_title": "已验证官网站内公开链接",
            "source_type": "official",
            "document_type": cls._kind(url),
            "discovery_method": method,
            "match_reason": "由已验证官网的公开导航或 sitemap 发现；待单独预检和任务相关性校验",
            "estimated_reliability": 0.92,
            "metadata": {
                "parent_url": parent_url,
                "official_domain": official_domain,
                "discovery_depth": depth,
                "discovered_from": method,
            },
        }

    @staticmethod
    def _links(page: FetchedOfficialPage) -> Iterable[tuple[str, str]]:
        soup = BeautifulSoup(page.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if href:
                yield urljoin(page.final_url, href), anchor.get_text(" ", strip=True)

    @staticmethod
    def _sitemap_urls(page: FetchedOfficialPage) -> Iterable[str]:
        # XML namespace 与 sitemapindex/urlset 均可退化为 loc 标签扫描。
        for value in re.findall(r"<loc[^>]*>\s*(.*?)\s*</loc>", page.text, flags=re.I | re.S):
            url = re.sub(r"\s+", "", value)
            if url:
                yield url

    def discover(
        self,
        *,
        official_domains: Iterable[str],
        official_entry_urls: Iterable[str] = (),
        known_report_paths: Mapping[str, Iterable[str]] | None = None,
        target_period: str,
    ) -> list[dict[str, object]]:
        """返回站内公开文档候选，不抛出单站 HTTP 失败。"""
        domains = {
            str(domain).strip().lower().removeprefix("www.")
            for domain in official_domains if str(domain).strip()
        }
        if not domains:
            return []
        queue: deque[tuple[str, int, str]] = deque()
        candidate_urls: set[str] = set()
        candidates: list[dict[str, object]] = []
        for entry in official_entry_urls:
            url = self._normalise_url(str(entry).strip())
            if self._same_official_domain(url, domains):
                queue.append((url, 0, "official_site_entry"))
        for domain in sorted(domains):
            # Publisher Profile 的路径只由“曾成功的 official 来源”派生。这里
            # 仅将明确的 {year} 替换为本次目标年，再作为独立候选交给后续
            # UrlProbe；不能因模板存在就假定 URL 可访问或内容符合任务。
            raw_paths = (known_report_paths or {}).get(domain, ())
            for raw_path in raw_paths:
                path = str(raw_path or "").strip()
                if not path:
                    continue
                candidate_url = self._normalise_url(
                    urljoin(f"https://{domain}/", path.replace("{year}", str(target_period)))
                )
                if not self._same_official_domain(candidate_url, domains) or candidate_url in candidate_urls:
                    continue
                candidate_urls.add(candidate_url)
                candidates.append(self._candidate(
                    url=candidate_url, text="已验证发布方报告路径",
                    parent_url=f"https://{domain}/", depth=1,
                    method="official_site_known_report_path", official_domain=domain,
                ))
            queue.append((f"https://{domain}/", 0, "official_site_home"))
            queue.append((f"https://{domain}/sitemap.xml", 0, "official_site_sitemap"))

        visited: set[str] = set()
        while queue and len(visited) < self.max_pages:
            url, depth, entry_method = queue.popleft()
            url = self._normalise_url(url)
            if url in visited or not self._same_official_domain(url, domains):
                continue
            visited.add(url)
            try:
                page = self._fetch(url)
            except requests.RequestException:
                continue
            except Exception:
                # 官网单页格式异常不能阻断同一官方域名中的其他已排队入口。
                continue
            if page.status_code < 200 or page.status_code >= 400:
                continue
            final_url = self._normalise_url(page.final_url or url)
            if not self._same_official_domain(final_url, domains):
                continue
            official_domain = self._host(final_url)
            is_sitemap = "xml" in page.content_type.lower() or final_url.lower().endswith(".xml")
            if is_sitemap:
                for found in self._sitemap_urls(page):
                    found = self._normalise_url(found)
                    if not self._same_official_domain(found, domains):
                        continue
                    if self._is_document_link(found, "", str(target_period)) and found not in candidate_urls:
                        candidate_urls.add(found)
                        candidates.append(self._candidate(
                            url=found, text=found, parent_url=final_url, depth=depth + 1,
                            method="official_site_sitemap", official_domain=official_domain,
                        ))
                    elif depth < self.max_depth and self._is_navigation_link(found, "", str(target_period)):
                        queue.append((found, depth + 1, "official_site_sitemap"))
                continue
            if "html" not in page.content_type.lower() and "<html" not in page.text.lower():
                continue
            for found, text in self._links(page):
                found = self._normalise_url(found)
                if not self._same_official_domain(found, domains):
                    continue
                if self._is_document_link(found, text, str(target_period)):
                    if found not in candidate_urls:
                        candidate_urls.add(found)
                        candidates.append(self._candidate(
                            url=found, text=text, parent_url=final_url, depth=depth + 1,
                            method="official_site_navigation", official_domain=official_domain,
                        ))
                elif depth < self.max_depth and self._is_navigation_link(found, text, str(target_period)):
                    queue.append((found, depth + 1, entry_method))
        return candidates
