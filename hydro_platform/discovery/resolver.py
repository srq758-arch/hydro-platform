"""Discovery 协调器：四级发现流程（设计文档 §7）。

按顺序尝试：
1. Level 1: GEM Wiki / Official Source Finder
2. Level 2: Authority Source Finder
3. Level 3: Google Custom Search（配置凭据时）
4. Level 4: DeepSeek 辅助发现（配置凭据时）

找到足够候选后提前返回，避免不必要的搜索。
"""

from __future__ import annotations
from typing import List
import sqlite3

from ..common.logging_setup import get_logger
from ..reliability.scorer import ReliabilityScorer
from .official import OfficialSourceFinder, SourceCandidate
from .authority import AuthoritySourceFinder
from .deepseek_search import DeepSeekSourceFinder
from .google_search import GoogleSearchConfig, GoogleSearchDiscovery

logger = get_logger(__name__)


class DiscoveryResolver:
    """数据源发现协调器"""

    def __init__(self, conn: sqlite3.Connection, deepseek_api_key: str = None):
        self.conn = conn
        self.scorer = ReliabilityScorer()

        # 初始化各级 Finder
        self.official_finder = OfficialSourceFinder(conn)
        self.authority_finder = AuthoritySourceFinder(conn)
        self.deepseek_finder = DeepSeekSourceFinder(api_key=deepseek_api_key)
        self.google_finder = None
        if GoogleSearchConfig.is_configured():
            api_key, engine_id = GoogleSearchConfig.from_env()
            self.google_finder = GoogleSearchDiscovery(api_key, engine_id)
            logger.info("Google Custom Search 来源发现已启用")
        else:
            logger.info("Google Custom Search 未配置，跳过该可选发现通道")

    def discover(
        self,
        task: dict,
        min_candidates: int = 3,
        max_candidates: int = 10
    ) -> List[dict]:
        """执行四级发现

        Args:
            task: 任务信息
            min_candidates: 最少候选数（达到后停止低级别发现）
            max_candidates: 最多候选数（截断）

        Returns:
            排序后的候选来源列表（按评分降序）
        """
        all_candidates = []

        logger.info(f"开始 Discovery: entity_id={task.get('entity_id')}, period={task.get('target_period')}")

        # Level 1: 官方来源
        logger.info("Level 1: 官方来源发现")
        official_candidates = self.official_finder.find(task)
        all_candidates.extend([c.to_dict() for c in official_candidates])

        if len(all_candidates) >= min_candidates:
            logger.info(f"Level 1 已找到足够候选 ({len(all_candidates)})，跳过后续级别")
        else:
            # Level 2: 权威来源
            logger.info("Level 2: 权威来源发现")
            authority_candidates = self.authority_finder.find(task)
            all_candidates.extend([c.to_dict() for c in authority_candidates])

            # Level 3: 可验证的搜索 API（可选，未配置则跳过）
            if len(all_candidates) < min_candidates:
                if self.google_finder:
                    logger.info("Level 3: Google Custom Search")
                    google_candidates = self.google_finder.find(task, limit=5)
                    all_candidates.extend([c.to_dict() for c in google_candidates])
                    logger.info(f"Level 3 找到 {len(google_candidates)} 个候选")
                else:
                    logger.info("Level 3: Google Custom Search 未配置")

            # Level 4: DeepSeek 智能搜索（可选）
            if len(all_candidates) < min_candidates:
                logger.info("Level 4: DeepSeek 智能搜索")
                if self.deepseek_finder.enabled:
                    deepseek_candidates = self.deepseek_finder.find(task, max_candidates=5)
                    all_candidates.extend(deepseek_candidates)
                    logger.info(f"Level 4 找到 {len(deepseek_candidates)} 个候选")
                else:
                    logger.info("Level 4: DeepSeek未启用（未设置API Key）")

        # 如果没有找到任何候选
        if not all_candidates:
            logger.warning("Discovery 未找到任何候选来源")
            return []

        # 使用 Reliability Scorer 排序
        logger.info(f"对 {len(all_candidates)} 个候选进行评分排序")
        ranked_candidates = self.scorer.rank_sources(all_candidates, task)

        # 截断到 max_candidates
        final_candidates = ranked_candidates[:max_candidates]

        logger.info(f"Discovery 完成: 返回 {len(final_candidates)} 个候选（已排序）")

        # 打印 Top 3 候选
        for i, candidate in enumerate(final_candidates[:3], 1):
            logger.info(
                f"  #{i} {candidate['url']} "
                f"(评分: {candidate.get('combined_score', 0):.2f}, "
                f"类型: {candidate['source_type']})"
            )

        return final_candidates
