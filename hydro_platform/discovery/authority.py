"""Level 2: 权威来源发现（设计文档 §7.1）。

查询权威数据库和国际组织：IEA, World Bank, IRENA, etc.
"""

from __future__ import annotations
from typing import List
import sqlite3

from ..common.logging_setup import get_logger
from .official import SourceCandidate

logger = get_logger(__name__)


class AuthoritySourceFinder:
    """权威来源查找器"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

        # 权威数据源列表
        self.authority_sources = {
            "IEA": {
                "base_url": "https://www.iea.org/data-and-statistics",
                "reliability": 0.90
            },
            "World Bank": {
                "base_url": "https://data.worldbank.org/",
                "reliability": 0.90
            },
            "IRENA": {
                "base_url": "https://www.irena.org/Statistics",
                "reliability": 0.85
            },
            "EIA": {
                "base_url": "https://www.eia.gov/international/data/",
                "reliability": 0.95
            },
            # 中国权威来源
            "国家能源局": {
                "base_url": "http://www.nea.gov.cn/",
                "reliability": 0.95
            }
        }

    def find(self, task: dict) -> List[SourceCandidate]:
        """查找权威来源

        策略：
        1. 根据电站国家选择对应的权威数据库
        2. 构造查询 URL
        3. 返回候选

        注意：大部分权威来源提供国家级总量，不提供单站数据
        因此权威来源主要用于交叉验证，而非主要数据源
        """
        candidates = []

        entity_id = task.get("entity_id")
        target_year = int(task.get("target_period", 0)) if task.get("target_period") else None

        # 查询电站国家
        station = self._get_station_info(entity_id)
        if not station:
            return candidates

        country = station.get("country", "")

        # 根据国家选择权威来源
        if country == "China":
            # 中国电站：国家能源局
            candidates.append(SourceCandidate(
                url=f"http://www.nea.gov.cn/",
                source_type="authority",
                document_type="html",
                match_reason="国家能源局官网",
                estimated_reliability=0.90,
                covered_year=target_year
            ))

        elif country == "United States":
            # 美国电站：EIA
            candidates.append(SourceCandidate(
                url=f"https://www.eia.gov/electricity/data.php",
                source_type="authority",
                document_type="html",
                match_reason="EIA 电力数据",
                estimated_reliability=0.95,
                covered_year=target_year
            ))

        else:
            # 其他国家：IEA, World Bank
            candidates.append(SourceCandidate(
                url="https://www.iea.org/data-and-statistics",
                source_type="authority",
                document_type="html",
                match_reason="IEA 数据库",
                estimated_reliability=0.85,
                covered_year=None
            ))

        logger.info(f"Level 2 权威来源: 共 {len(candidates)} 个候选")
        return candidates

    def _get_station_info(self, entity_id: str) -> dict:
        """获取电站信息"""
        cursor = self.conn.execute("""
            SELECT entity_id, canonical_name, country
            FROM stations
            WHERE entity_id = ?
        """, (entity_id,))

        row = cursor.fetchone()
        return dict(row) if row else {}
