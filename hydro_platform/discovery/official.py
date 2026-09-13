"""Level 1: 官方来源发现（设计文档 §7.1）。

从电站 official_website 生成年报 URL 候选，解析 GEM Wiki References。
"""

from __future__ import annotations
from typing import Callable, List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import sqlite3

import requests
from bs4 import BeautifulSoup

from ..common.logging_setup import get_logger

logger = get_logger(__name__)


class SourceCandidate:
    """候选来源"""
    def __init__(
        self,
        url: str,
        source_type: str,
        document_type: str,
        match_reason: str,
        estimated_reliability: float = 0.5,
        covered_year: int = None,
        *,
        canonical_url: str | None = None,
        link_text: str | None = None,
        section_title: str | None = None,
        discovery_method: str | None = None,
    ):
        self.url = url
        self.source_type = source_type
        self.document_type = document_type
        self.match_reason = match_reason
        self.estimated_reliability = estimated_reliability
        self.covered_year = covered_year
        self.canonical_url = canonical_url or url
        self.link_text = link_text
        self.section_title = section_title
        self.discovery_method = discovery_method

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "source_type": self.source_type,
            "document_type": self.document_type,
            "match_reason": self.match_reason,
            "estimated_reliability": self.estimated_reliability,
            "covered_year": self.covered_year,
            "canonical_url": self.canonical_url,
            "link_text": self.link_text,
            "section_title": self.section_title,
            "discovery_method": self.discovery_method,
        }


class OfficialSourceFinder:
    """官方来源查找器"""

    _SECTION_MARKERS = ("reference", "source", "external link", "citation", "参考", "来源", "外部链接")
    _OFFICIAL_MARKERS = ("official", "website", "operator", "owner", "company", "developer", "government", "官网", "官方网站", "运营", "业主")
    _LOW_VALUE_DOMAINS = ("facebook.com", "twitter.com", "x.com", "linkedin.com", "youtube.com", "instagram.com")
    # GEM/Tracker 与 Wayback 是有价值的背景或历史入口，但不是“电站官方来源”；
    # 首轮发现不返回它们，后续专门的存档回退策略再显式处理。
    _EXCLUDED_DOMAINS = ("globalenergymonitor.org", "web.archive.org")
    _TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}

    def __init__(self, conn: sqlite3.Connection, *, fetch_html: Callable[[str], str] | None = None, timeout: float = 15.0):
        self.conn = conn
        self.timeout = timeout
        self._fetch_html = fetch_html or self._request_html

    def find(self, task: dict) -> List[SourceCandidate]:
        """查找官方来源

        策略：
        1. 从 stations 表获取 official_website
        2. 生成常见年报 URL 模式
        3. 解析 GEM Wiki 提取 References（待实现）

        Args:
            task: {
                "entity_id": "GEM-G100000601208",
                "entity_name": "三峡",
                "target_period": "2024",
                "metric": "generation"
            }

        Returns:
            候选来源列表
        """
        candidates = []

        entity_id = task.get("entity_id")
        target_year = int(task.get("target_period", 0)) if task.get("target_period") else None

        # 1. 查询电站信息
        station = self._get_station_info(entity_id)
        if not station:
            logger.warning(f"未找到电站信息: {entity_id}")
            return candidates

        # 2. 从 official_website 生成年报 URL（检查 source_url 字段）
        # source_url 是 seed 数据集的下载来源，不能被误当成电站官网。
        official_website = station.get("official_website")
        if official_website:
            url_candidates = self._generate_annual_report_urls(
                official_website,
                target_year
            )
            candidates.extend(url_candidates)
            logger.info(f"从官方网站生成 {len(url_candidates)} 个候选 URL")

        # 3. 从 GEM Wiki 提取 References
        gem_wiki_url = station.get("gem_wiki_url")
        if gem_wiki_url:
            wiki_candidates = self._parse_gem_wiki_references(
                gem_wiki_url,
                target_year
            )
            candidates.extend(wiki_candidates)
            logger.info(f"从 GEM Wiki 提取 {len(wiki_candidates)} 个候选")

        logger.info(f"Level 1 官方来源发现: 共 {len(candidates)} 个候选")
        return candidates

    def _get_station_info(self, entity_id: str) -> Optional[dict]:
        """从数据库获取电站信息"""
        cursor = self.conn.execute("""
            SELECT
                entity_id,
                canonical_name,
                source_url,
                gem_wiki_url,
                operator,
                country
            FROM stations
            WHERE entity_id = ?
        """, (entity_id,))

        row = cursor.fetchone()
        return dict(row) if row else None

    def _generate_annual_report_urls(
        self,
        base_url: str,
        year: int
    ) -> List[SourceCandidate]:
        """生成常见年报 URL 模式

        常见模式：
        - {base}/annual-report-{year}.pdf
        - {base}/reports/{year}/annual-report.pdf
        - {base}/investor-relations/reports/{year}
        - {base}/en/reports/{year}
        - {base}/about-us/annual-reports/{year}
        - {base}/sustainability/reports/{year}
        - {base}/ir/reports/{year}.pdf
        - {base}/documents/annual-report-{year}.pdf
        """
        candidates = []

        if not year:
            logger.debug("未指定年份，跳过年报 URL 生成")
            return candidates

        # 确保 base_url 以 / 结尾
        if not base_url.endswith('/'):
            base_url += '/'

        # 常见 URL 模式
        patterns = [
            f"annual-report-{year}.pdf",
            f"reports/{year}/annual-report.pdf",
            f"investor-relations/reports/{year}",
            f"en/reports/{year}",
            f"about-us/annual-reports/{year}",
            f"sustainability/reports/{year}",
            f"ir/reports/{year}.pdf",
            f"documents/annual-report-{year}.pdf",
            f"media/reports/annual-{year}.pdf",
            f"annual-reports/{year}",
        ]

        for pattern in patterns:
            url = urljoin(base_url, pattern)

            candidates.append(SourceCandidate(
                url=url,
                source_type="official",
                document_type="pdf" if pattern.endswith(".pdf") else "html",
                match_reason=f"生成自官方网站: {pattern}",
                estimated_reliability=0.85,
                covered_year=year
            ))

        return candidates

    def _parse_gem_wiki_references(
        self,
        gem_wiki_url: str,
        target_year: int
    ) -> List[SourceCandidate]:
        """下载并解析 GEM Wiki 的参考/外链区，返回站外可审阅候选。

        GEM 页面本身只是发现入口，绝不伪装为“官方来源”。候选保留链接文字和
        所在章节，供用户确认；此方法不写库，也不会创建采集任务。
        """
        try:
            return self._extract_external_links(gem_wiki_url, self._fetch_html(gem_wiki_url), target_year)
        except Exception as exc:
            logger.warning("GEM Wiki 外链解析失败 %s: %s", gem_wiki_url, exc)
            return []

    def _request_html(self, url: str) -> str:
        response = requests.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": "HydroPlatform/1.0 (+source-discovery)"},
        )
        response.raise_for_status()
        return response.text

    def _extract_external_links(self, gem_wiki_url: str, html: str, target_year: int | None) -> List[SourceCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        gem_host = urlparse(gem_wiki_url).netloc.lower().removeprefix("www.")
        seen: set[str] = set()
        candidates: list[SourceCandidate] = []

        for anchor, section_title in self._reference_anchors(soup):
            raw_url = (anchor.get("href") or "").strip()
            url = self._canonicalize_url(urljoin(gem_wiki_url, raw_url))
            parsed = urlparse(url)
            host = parsed.netloc.lower().removeprefix("www.")
            link_text = " ".join(anchor.stripped_strings)
            context = f"{section_title} {link_text}".lower()
            if (
                parsed.scheme not in {"http", "https"}
                or not host or host == gem_host or url in seen
                or any(host == domain or host.endswith(f".{domain}") for domain in self._LOW_VALUE_DOMAINS)
                or any(host == domain or host.endswith(f".{domain}") for domain in self._EXCLUDED_DOMAINS)
            ):
                continue
            seen.add(url)
            source_type, reliability = self._classify_external_link(host, context)
            candidates.append(SourceCandidate(
                url=url,
                canonical_url=url,
                source_type=source_type,
                document_type=self._guess_document_type(url),
                match_reason=f"GEM Wiki「{section_title}」外链「{link_text or host}」",
                estimated_reliability=reliability,
                covered_year=target_year if target_year and str(target_year) in url else None,
                link_text=link_text or None,
                section_title=section_title,
                discovery_method="gem_wiki_external_link",
            ))
        candidates.sort(key=lambda item: item.estimated_reliability, reverse=True)
        logger.info("GEM Wiki 外链解析完成: %s 个候选", len(candidates))
        return candidates[:20]

    def _reference_anchors(self, soup: BeautifulSoup):
        """提取参考相关章节的链接；版式变化时退化为明确标注官方的链接。"""
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        found_section = False
        for heading in headings:
            title = " ".join(heading.stripped_strings)
            if not any(marker in title.lower() for marker in self._SECTION_MARKERS):
                continue
            found_section = True
            level = int(heading.name[1])
            node = heading.next_sibling
            while node:
                if getattr(node, "name", None) in {"h1", "h2", "h3", "h4", "h5", "h6"} and int(node.name[1]) <= level:
                    break
                if getattr(node, "find_all", None):
                    for anchor in node.find_all("a", href=True):
                        yield anchor, title
                node = node.next_sibling
        if found_section:
            return
        for anchor in soup.find_all("a", href=True):
            label = " ".join(anchor.stripped_strings).lower()
            if any(marker in label for marker in self._OFFICIAL_MARKERS):
                yield anchor, "Official links"

    @classmethod
    def _canonicalize_url(cls, url: str) -> str:
        parsed = urlparse(url)
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                 if key.lower() not in cls._TRACKING_KEYS]
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", urlencode(query), ""))

    @staticmethod
    def _guess_document_type(url: str) -> str:
        path = urlparse(url).path.lower()
        if path.endswith(".pdf"):
            return "pdf"
        if path.endswith((".xlsx", ".xls", ".csv")):
            return "excel"
        if path.endswith(".json"):
            return "json"
        return "html"

    @classmethod
    def _classify_external_link(cls, host: str, context: str) -> tuple[str, float]:
        if ".gov" in host or host.endswith(".gov.cn"):
            return "authority", 0.95
        if any(marker in context for marker in cls._OFFICIAL_MARKERS):
            return "official", 0.92
        if host.endswith(".org"):
            return "reference", 0.72
        return "reference", 0.65
