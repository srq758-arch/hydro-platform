"""Level 4: 深度探索 - 网站导航爬取（设计文档 §7.4）。

爬取网站首页导航链接，发现报告和数据页面。
"""

from __future__ import annotations
from typing import List
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from ..common.logging_setup import get_logger
from .official import SourceCandidate

logger = get_logger(__name__)


class NavigationCrawler:
    """网站导航爬取器

    从网站首页提取导航链接，查找包含报告、数据的页面。
    策略：
    - 查找<nav>标签
    - 查找常见导航class（menu, navigation, navbar）
    - 过滤包含关键词的链接（report, data, investor relations）
    """

    def __init__(self, timeout: int = 10, max_depth: int = 1):
        """初始化导航爬取器

        Args:
            timeout: HTTP请求超时时间（秒）
            max_depth: 最大爬取深度（1=仅首页导航，2=导航+二级页面）
        """
        self.timeout = timeout
        self.max_depth = max_depth

    def crawl(
        self,
        base_url: str,
        year: int | None = None,
        metric: str | None = None
    ) -> List[SourceCandidate]:
        """爬取网站导航发现数据源

        Args:
            base_url: 网站根URL（如 https://www.ctg.com.cn）
            year: 目标年份（可选）
            metric: 指标类型（可选）

        Returns:
            候选来源列表
        """
        # 规范化base_url
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url

        try:
            # 抓取首页
            logger.debug(f"爬取网站导航: {base_url}")
            nav_links = self._crawl_navigation(base_url)

            # 过滤相关链接
            filtered_links = self._filter_relevant_links(nav_links, year, metric)

            # 转换为SourceCandidate
            candidates = []
            for link in filtered_links:
                candidate = self._to_source_candidate(link, year, metric, depth=1)
                candidates.append(candidate)

            # 可选：爬取二级页面
            if self.max_depth >= 2 and candidates:
                logger.debug(f"深度爬取二级页面（{len(candidates[:3])} 个链接）")
                for link in filtered_links[:3]:  # 限制数量避免过度爬取
                    try:
                        child_candidates = self._crawl_child_page(link, year, metric)
                        candidates.extend(child_candidates)
                    except Exception as e:
                        logger.debug(f"二级页面爬取失败 {link}: {e}")

            logger.info(f"导航爬取: 共 {len(candidates)} 个候选")
            return candidates

        except Exception as e:
            logger.error(f"导航爬取失败: {e}")
            return []

    def _crawl_navigation(self, homepage_url: str) -> List[dict]:
        """抓取首页导航链接

        Args:
            homepage_url: 首页URL

        Returns:
            链接列表，每个包含 {'url': str, 'text': str}
        """
        response = requests.get(homepage_url, timeout=self.timeout)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # 查找导航元素
        nav_elements = []

        # 1. 标准<nav>标签
        nav_elements.extend(soup.find_all('nav'))

        # 2. 常见导航class
        nav_classes = ['menu', 'navigation', 'navbar', 'nav', 'header-menu', 'main-nav']
        for cls in nav_classes:
            nav_elements.extend(soup.find_all(['div', 'ul'], class_=lambda x: x and cls in x.lower()))

        links = []
        seen_urls = set()

        for nav in nav_elements:
            for a in nav.find_all('a', href=True):
                href = a['href']
                text = a.get_text(strip=True)

                # 构造完整URL
                full_url = urljoin(homepage_url, href)

                # 去重
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                # 过滤外部链接
                if not self._is_same_domain(homepage_url, full_url):
                    continue

                links.append({
                    'url': full_url,
                    'text': text
                })

        logger.debug(f"从导航提取 {len(links)} 个链接")
        return links

    def _filter_relevant_links(
        self,
        links: List[dict],
        year: int | None,
        metric: str | None
    ) -> List[str]:
        """过滤出相关的链接

        策略：
        - 链接文本包含关键词
        - URL路径包含关键词

        Args:
            links: 链接列表
            year: 目标年份（可选）
            metric: 指标类型（可选）

        Returns:
            过滤后的URL列表
        """
        keywords = [
            'report', 'annual', 'investor', 'data', 'statistic',
            'publication', 'disclosure', 'performance', 'sustainability',
            'media', 'news', 'press'
        ]

        # 根据metric添加特定关键词
        if metric == 'generation':
            keywords.extend(['generation', 'production', 'electricity'])
        elif metric == 'capacity':
            keywords.extend(['capacity', 'project', 'construction'])

        filtered = []
        for link in links:
            url = link['url']
            text = link['text'].lower()
            url_lower = url.lower()

            # 检查链接文本或URL是否包含关键词
            has_keyword = any(kw in text or kw in url_lower for kw in keywords)
            if not has_keyword:
                continue

            filtered.append(url)

        # 去重
        filtered = list(set(filtered))

        return filtered

    def _crawl_child_page(
        self,
        page_url: str,
        year: int | None,
        metric: str | None
    ) -> List[SourceCandidate]:
        """爬取二级页面查找PDF和数据链接

        Args:
            page_url: 二级页面URL
            year: 目标年份
            metric: 指标类型

        Returns:
            候选来源列表
        """
        try:
            response = requests.get(page_url, timeout=self.timeout)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            candidates = []

            # 查找所有链接
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text(strip=True)

                # 构造完整URL
                full_url = urljoin(page_url, href)

                # 只关注PDF或包含年份的链接
                if not (full_url.lower().endswith('.pdf') or (year and str(year) in full_url)):
                    continue

                # 检查是否相关
                url_lower = full_url.lower()
                text_lower = text.lower()
                relevant_keywords = ['report', 'annual', 'generation', 'capacity', 'statistic']

                if any(kw in url_lower or kw in text_lower for kw in relevant_keywords):
                    candidate = self._to_source_candidate(full_url, year, metric, depth=2)
                    candidates.append(candidate)

            return candidates

        except Exception as e:
            logger.debug(f"二级页面爬取失败: {e}")
            return []

    def _is_same_domain(self, base_url: str, target_url: str) -> bool:
        """检查是否同域名

        Args:
            base_url: 基础URL
            target_url: 目标URL

        Returns:
            True如果同域名
        """
        try:
            base_domain = urlparse(base_url).netloc
            target_domain = urlparse(target_url).netloc
            return base_domain == target_domain
        except Exception:
            return False

    def _to_source_candidate(
        self,
        url: str,
        year: int | None,
        metric: str | None,
        depth: int
    ) -> SourceCandidate:
        """将URL转换为SourceCandidate

        Args:
            url: 目标URL
            year: 目标年份
            metric: 指标类型
            depth: 爬取深度（1=导航，2=二级页面）

        Returns:
            SourceCandidate对象
        """
        # 推断文档类型
        doc_type = 'pdf' if url.lower().endswith('.pdf') else 'html'

        # 估计可靠性
        reliability = self._estimate_reliability(url, doc_type, depth)

        # 构造匹配原因
        source_desc = "导航链接" if depth == 1 else "二级页面"
        match_reason = f"{source_desc}发现: {url.split('/')[-1]}"

        return SourceCandidate(
            url=url,
            source_type='navigation',
            document_type=doc_type,
            match_reason=match_reason,
            estimated_reliability=reliability,
            covered_year=year
        )

    def _estimate_reliability(self, url: str, doc_type: str, depth: int) -> float:
        """估计来源可靠性

        导航链接通常是官方内容，可靠性较高

        Args:
            url: 目标URL
            doc_type: 文档类型
            depth: 爬取深度

        Returns:
            可靠性分数 [0.0, 1.0]
        """
        # 导航链接基础分数
        base_score = 0.65 if depth == 1 else 0.70

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


class NavigationConfig:
    """导航爬取配置"""

    @staticmethod
    def get_default_timeout() -> int:
        """获取默认超时时间

        Returns:
            超时时间（秒）
        """
        return 10

    @staticmethod
    def get_default_max_depth() -> int:
        """获取默认最大深度

        Returns:
            最大深度
        """
        return 1

    @staticmethod
    def get_max_links_per_page() -> int:
        """获取每页最大链接数

        避免处理过多链接消耗过多资源

        Returns:
            最大链接数
        """
        return 50
