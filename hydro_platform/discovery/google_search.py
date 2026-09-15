"""Level 3: Google搜索引擎发现（设计文档 §7.3）。

使用Google Custom Search API自动发现包含目标数据的网页。
"""

from __future__ import annotations
from typing import List, Optional
import requests
from urllib.parse import urlparse

from ..common.logging_setup import get_logger
from .official import SourceCandidate

logger = get_logger(__name__)


class GoogleSearchDiscovery:
    """Google搜索引擎数据源发现器

    使用Google Custom Search API查找包含电站数据的网页。
    需要配置：
    - API Key（从 Google Cloud Console 获取）
    - Search Engine ID（从 Programmable Search Engine 创建）

    免费额度：100次查询/天
    文档：https://developers.google.com/custom-search
    """

    def __init__(self, api_key: str, search_engine_id: str):
        """初始化Google搜索发现器

        Args:
            api_key: Google API Key
            search_engine_id: Custom Search Engine ID (cx参数)
        """
        self.api_key = api_key
        self.cx = search_engine_id
        self.base_url = "https://www.googleapis.com/customsearch/v1"

    def find(self, task: dict, limit: int = 10) -> List[SourceCandidate]:
        """查找数据源

        Args:
            task: 任务信息 {
                "entity_id": "...",
                "entity_name": "Three Gorges Dam",
                "country": "CN",
                "target_period": "2023",
                "metric": "generation"
            }
            limit: 返回结果数量限制（最大10）

        Returns:
            候选来源列表
        """
        entity_name = task.get("entity_name", "")
        country = task.get("country", "")
        year = task.get("target_period")
        metric = task.get("metric", "generation")

        if not entity_name:
            logger.warning("entity_name为空，跳过Google搜索")
            return []

        try:
            # 构造搜索查询
            query = self._build_query(entity_name, country, year, metric)
            logger.info(f"Google搜索查询: {query}")

            # 调用API
            results = self._call_google_api(query, min(limit, 10))

            # 转换为SourceCandidate
            candidates = []
            for item in results:
                candidate = self._to_source_candidate(item, year, metric)
                candidates.append(candidate)

            logger.info(f"Google搜索发现: {len(candidates)} 个候选")
            return candidates

        except Exception as e:
            logger.error(f"Google搜索失败: {e}")
            return []

    def _build_query(
        self,
        entity_name: str,
        country: str,
        year: Optional[int],
        metric: str
    ) -> str:
        """构造搜索查询字符串

        策略：
        - 使用引号包裹电站名称（精确匹配）
        - 包含国家名称（提高相关性）
        - 包含年份（如果指定）
        - 根据metric添加关键词

        示例：
        - "Three Gorges Dam" China 2023 generation GWh
        - "Itaipu Dam" Brazil 2023 "electricity production" TWh
        - "Belo Monte" Brazil capacity MW installed

        Args:
            entity_name: 电站名称
            country: 国家代码或名称
            year: 目标年份
            metric: 指标类型（generation/capacity）

        Returns:
            查询字符串
        """
        terms = []

        # 1. 电站名称（引号精确匹配）
        terms.append(f'"{entity_name}"')

        # 2. 国家（可选）
        if country:
            # 将国家代码转换为全名（简单映射）
            country_map = {
                'CN': 'China',
                'BR': 'Brazil',
                'US': 'United States',
                'CA': 'Canada',
                'RU': 'Russia',
                'IN': 'India',
                'VE': 'Venezuela',
                'CO': 'Colombia',
                'NO': 'Norway',
                'TR': 'Turkey'
            }
            country_name = country_map.get(country, country)
            terms.append(country_name)

        # 3. 年份（可选）
        if year:
            terms.append(str(year))

        # 4. 指标关键词
        if metric == 'generation':
            # 发电量相关词汇
            terms.append('(generation OR "electricity production" OR output)')
            terms.append('(GWh OR TWh OR "billion kWh")')
        elif metric == 'capacity':
            # 装机容量相关词汇
            terms.append('(capacity OR "installed capacity" OR power)')
            terms.append('(MW OR GW OR megawatt)')

        return ' '.join(terms)

    def _call_google_api(self, query: str, limit: int, *, timeout: float | None = None) -> List[dict]:
        """调用Google Custom Search API

        Args:
            query: 搜索查询字符串
            limit: 结果数量（最大10）

        Returns:
            搜索结果列表，每个结果包含：
            - title: 标题
            - link: URL
            - snippet: 摘要
            - displayLink: 显示域名

        Raises:
            requests.HTTPError: API调用失败
        """
        params = {
            'key': self.api_key,
            'cx': self.cx,
            'q': query,
            'num': min(limit, 10)  # API限制最多10条
        }

        response = requests.get(self.base_url, params=params, timeout=timeout or 10)
        response.raise_for_status()

        data = response.json()
        items = data.get('items', [])

        logger.debug(f"Google API返回 {len(items)} 条结果")
        return items

    def _to_source_candidate(
        self,
        item: dict,
        year: Optional[int],
        metric: str
    ) -> SourceCandidate:
        """将Google搜索结果转换为SourceCandidate

        Args:
            item: Google搜索结果项
            year: 目标年份
            metric: 指标类型

        Returns:
            SourceCandidate对象
        """
        url = item.get('link', '')
        title = item.get('title', '')
        snippet = item.get('snippet', '')

        # 推断文档类型
        doc_type = self._guess_document_type(url)

        # 估计可靠性（基于域名和文档类型）
        reliability = self._estimate_reliability(url, doc_type)

        # 构造匹配原因
        match_reason = f"Google搜索结果"
        if snippet:
            match_reason += f": {snippet[:100]}"

        return SourceCandidate(
            url=url,
            source_type='search_result',
            document_type=doc_type,
            match_reason=match_reason,
            estimated_reliability=reliability,
            covered_year=year
        )

    def _guess_document_type(self, url: str) -> str:
        """根据URL推断文档类型

        Args:
            url: 目标URL

        Returns:
            文档类型: pdf/html/json/xml
        """
        url_lower = url.lower()

        if url_lower.endswith('.pdf'):
            return 'pdf'
        elif url_lower.endswith('.json'):
            return 'json'
        elif url_lower.endswith('.xml'):
            return 'xml'
        elif url_lower.endswith('.csv'):
            return 'csv'
        else:
            return 'html'

    def _estimate_reliability(self, url: str, doc_type: str) -> float:
        """估计来源可靠性

        策略：
        - 政府/官方域名: 0.8-0.9
        - .edu/.org域名: 0.7-0.8
        - PDF文档: +0.1
        - 其他: 0.5-0.6

        Args:
            url: 目标URL
            doc_type: 文档类型

        Returns:
            可靠性分数 [0.0, 1.0]
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # 基础分数
            base_score = 0.5

            # 域名类型加分
            if any(x in domain for x in ['.gov', '.gov.', 'government']):
                base_score = 0.85
            elif any(x in domain for x in ['.edu', '.org', 'official']):
                base_score = 0.75
            elif any(x in domain for x in ['wikipedia', 'energy.gov', 'iea.org']):
                base_score = 0.70

            # 文档类型加分
            if doc_type == 'pdf':
                base_score += 0.1

            # 限制在[0.0, 1.0]范围
            return min(base_score, 1.0)

        except Exception:
            return 0.5


class GoogleSearchConfig:
    """Google搜索配置管理

    从环境变量或配置文件加载API密钥
    """

    @staticmethod
    def from_env() -> tuple[str, str]:
        """从环境变量加载配置

        需要设置：
        - GOOGLE_API_KEY
        - GOOGLE_SEARCH_ENGINE_ID

        Returns:
            (api_key, search_engine_id)

        Raises:
            ValueError: 环境变量未设置
        """
        import os

        api_key = os.getenv('GOOGLE_API_KEY')
        engine_id = os.getenv('GOOGLE_SEARCH_ENGINE_ID')

        if not api_key or not engine_id:
            raise ValueError(
                "Google搜索需要配置环境变量:\n"
                "  GOOGLE_API_KEY=your_api_key\n"
                "  GOOGLE_SEARCH_ENGINE_ID=your_engine_id"
            )

        return api_key, engine_id

    @staticmethod
    def is_configured() -> bool:
        """检查是否已配置

        Returns:
            True如果环境变量已设置
        """
        import os
        return bool(os.getenv('GOOGLE_API_KEY') and os.getenv('GOOGLE_SEARCH_ENGINE_ID'))
