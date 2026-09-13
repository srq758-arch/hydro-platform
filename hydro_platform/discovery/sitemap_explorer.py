"""Level 4: 深度探索 - Sitemap解析（设计文档 §7.4）。

解析网站sitemap.xml发现PDF报告和数据页面链接。
"""

from __future__ import annotations
from typing import List
import requests
from xml.etree import ElementTree
from urllib.parse import urljoin, urlparse

from ..common.logging_setup import get_logger
from .official import SourceCandidate

logger = get_logger(__name__)


class SitemapExplorer:
    """Sitemap探索器

    从网站sitemap.xml中提取包含报告、数据的URL。
    常见sitemap位置：
    - /sitemap.xml
    - /sitemap_index.xml
    - /sitemap-reports.xml
    - /reports/sitemap.xml
    """

    def __init__(self, timeout: int = 10):
        """初始化Sitemap探索器

        Args:
            timeout: HTTP请求超时时间（秒）
        """
        self.timeout = timeout
        # XML命名空间
        self.ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

    def explore(
        self,
        base_url: str,
        year: int | None = None,
        metric: str | None = None
    ) -> List[SourceCandidate]:
        """探索网站sitemap发现数据源

        Args:
            base_url: 网站根URL（如 https://www.ctg.com.cn）
            year: 目标年份（可选，用于过滤）
            metric: 指标类型（可选，用于过滤）

        Returns:
            候选来源列表
        """
        # 规范化base_url
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url

        # 尝试常见sitemap位置
        sitemap_urls = self._get_sitemap_urls(base_url)

        all_urls = []
        for sitemap_url in sitemap_urls:
            try:
                logger.debug(f"尝试解析sitemap: {sitemap_url}")
                urls = self._parse_sitemap(sitemap_url)
                all_urls.extend(urls)

                if urls:
                    logger.info(f"从 {sitemap_url} 提取 {len(urls)} 个URL")

            except Exception as e:
                logger.debug(f"Sitemap解析失败 {sitemap_url}: {e}")

        # 过滤相关URL
        filtered_urls = self._filter_relevant_urls(all_urls, year, metric)

        # 转换为SourceCandidate
        candidates = []
        for url in filtered_urls:
            candidate = self._to_source_candidate(url, year, metric)
            candidates.append(candidate)

        logger.info(f"Sitemap探索: 共 {len(candidates)} 个候选")
        return candidates

    def _get_sitemap_urls(self, base_url: str) -> List[str]:
        """获取可能的sitemap URL列表

        Args:
            base_url: 网站根URL

        Returns:
            sitemap URL列表
        """
        return [
            urljoin(base_url, '/sitemap.xml'),
            urljoin(base_url, '/sitemap_index.xml'),
            urljoin(base_url, '/sitemap-reports.xml'),
            urljoin(base_url, '/reports/sitemap.xml'),
            urljoin(base_url, '/en/sitemap.xml'),
            urljoin(base_url, '/sitemap-misc.xml'),
        ]

    def _parse_sitemap(self, sitemap_url: str) -> List[str]:
        """解析单个sitemap文件

        Args:
            sitemap_url: sitemap URL

        Returns:
            提取的URL列表

        Raises:
            requests.RequestException: HTTP请求失败
            ElementTree.ParseError: XML解析失败
        """
        response = requests.get(sitemap_url, timeout=self.timeout)
        response.raise_for_status()

        # 解析XML
        root = ElementTree.fromstring(response.content)

        urls = []

        # 检查是否是sitemap索引（包含其他sitemap）
        sitemaps = root.findall('.//sm:sitemap/sm:loc', self.ns)
        if sitemaps:
            # 这是sitemap索引，递归解析子sitemap
            logger.debug(f"发现sitemap索引，包含 {len(sitemaps)} 个子sitemap")
            for sitemap_loc in sitemaps:
                try:
                    child_urls = self._parse_sitemap(sitemap_loc.text)
                    urls.extend(child_urls)
                except Exception as e:
                    logger.debug(f"子sitemap解析失败 {sitemap_loc.text}: {e}")
        else:
            # 这是普通sitemap，提取URL
            url_elements = root.findall('.//sm:url/sm:loc', self.ns)
            urls = [elem.text for elem in url_elements if elem.text]

        return urls

    def _filter_relevant_urls(
        self,
        urls: List[str],
        year: int | None,
        metric: str | None
    ) -> List[str]:
        """过滤出相关的URL

        策略：
        - 包含关键词：report, annual, generation, statistic, capacity
        - 文件类型：.pdf, .html
        - 可选：包含年份

        Args:
            urls: URL列表
            year: 目标年份（可选）
            metric: 指标类型（可选）

        Returns:
            过滤后的URL列表
        """
        keywords = [
            'report', 'annual', 'generation', 'statistic',
            'capacity', 'data', 'publication', 'disclosure',
            '.pdf', 'investor', 'sustainability', 'performance'
        ]

        # 根据metric添加特定关键词
        if metric == 'generation':
            keywords.extend(['electricity', 'production', 'output', 'gwh', 'twh'])
        elif metric == 'capacity':
            keywords.extend(['installed', 'power', 'mw', 'gw'])

        filtered = []
        for url in urls:
            url_lower = url.lower()

            # 检查是否包含相关关键词
            has_keyword = any(kw in url_lower for kw in keywords)
            if not has_keyword:
                continue

            # 可选：检查年份
            if year and str(year) not in url:
                # 允许±1年的容差
                if not (str(year-1) in url or str(year+1) in url):
                    continue

            filtered.append(url)

        # 去重
        filtered = list(set(filtered))

        return filtered

    def _to_source_candidate(
        self,
        url: str,
        year: int | None,
        metric: str | None
    ) -> SourceCandidate:
        """将URL转换为SourceCandidate

        Args:
            url: 目标URL
            year: 目标年份
            metric: 指标类型

        Returns:
            SourceCandidate对象
        """
        # 推断文档类型
        doc_type = 'pdf' if url.lower().endswith('.pdf') else 'html'

        # 估计可靠性
        reliability = self._estimate_reliability(url, doc_type)

        # 构造匹配原因
        match_reason = f"Sitemap发现: {url.split('/')[-1]}"

        return SourceCandidate(
            url=url,
            source_type='sitemap',
            document_type=doc_type,
            match_reason=match_reason,
            estimated_reliability=reliability,
            covered_year=year
        )

    def _estimate_reliability(self, url: str, doc_type: str) -> float:
        """估计来源可靠性

        Sitemap中的URL通常是官方内容，可靠性较高

        Args:
            url: 目标URL
            doc_type: 文档类型

        Returns:
            可靠性分数 [0.0, 1.0]
        """
        base_score = 0.7  # Sitemap来源基础分数较高

        # 域名加分
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            if any(x in domain for x in ['.gov', 'official']):
                base_score = 0.85
            elif any(x in domain for x in ['.edu', '.org']):
                base_score = 0.80
        except Exception:
            pass

        # PDF文档加分
        if doc_type == 'pdf':
            base_score += 0.05

        return min(base_score, 1.0)


class SitemapConfig:
    """Sitemap探索配置"""

    @staticmethod
    def get_default_timeout() -> int:
        """获取默认超时时间

        Returns:
            超时时间（秒）
        """
        return 10

    @staticmethod
    def get_max_urls_per_site() -> int:
        """获取每个网站最大URL数量

        避免处理过大的sitemap消耗过多资源

        Returns:
            最大URL数量
        """
        return 1000
