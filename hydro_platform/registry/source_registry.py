"""来源注册表：历史来源管理、可靠性评分、任务适配性评估（设计文档 §6.4）。

SourceRegistry 是记忆层，优先于 Discovery。每次任务先查历史来源，找到且有效则
直接使用；未找到或失效才触发 Discovery。来源成功后提升评分，失败后降低评分。
"""

from __future__ import annotations
from typing import Optional, List
from datetime import datetime, timedelta
import sqlite3
import uuid

from ..common.logging_setup import get_logger
from ..common.clock import now_iso

logger = get_logger(__name__)


class SourceRegistry:
    """来源注册表：管理历史来源、评分、预检"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def query_best_source(
        self,
        entity_id: str,
        metric: str,
        year: int = None,
        *,
        verified_only: bool = False,
    ) -> Optional[dict]:
        """查询历史最佳来源（优先于 Discovery）

        返回格式：
        {
            "source_id": "src_xxx",
            "source_url": "https://...",
            "canonical_url": "https://...",
            "access_method": "http",
            "source_reliability_score": 0.85,
            "last_success": "2026-09-07T10:30:00",
            "covered_year": 2024
        }

        查询逻辑：
        1. 查找 entity_id + metric 匹配的来源
        2. 过滤掉近期失败的来源（7天内失败 > 3次）
        3. 优先返回覆盖目标年份的来源
        4. 按 source_reliability_score 降序
        """
        sources = self.query_sources(
            entity_id=entity_id,
            metric=metric,
            year=year,
            limit=1,
            verified_only=verified_only,
        )
        return sources[0] if sources else None

    def query_sources(
        self,
        entity_id: str,
        metric: str,
        year: int | None = None,
        limit: int = 5,
        *,
        verified_only: bool = False,
    ) -> List[dict]:
        """按年份匹配和可靠性返回 Top-N 历史来源。

        ``verified_only`` 用于正式采集路径：只有至少一次完整采集/校验成功
        的来源才允许作为历史来源复用。刚被发现或仅完成下载但尚未通过事实
        校验的来源仍可通过默认查询返回，供管理和诊断页面查看，但不能反过来
        遮蔽下一次任务的 Discovery。
        """
        if limit < 1:
            return []
        logger.info(
            "查询历史来源队列: entity_id=%s, metric=%s, year=%s, limit=%s",
            entity_id, metric, year, limit,
        )

        # 查询条件
        verification_clause = """
            AND last_success IS NOT NULL
            AND COALESCE(success_count, 0) > 0
        """ if verified_only else ""
        query = f"""
            SELECT
                source_id,
                COALESCE(source_url, url) AS source_url,
                canonical_url,
                access_method,
                source_reliability_score,
                last_success,
                last_failure,
                covered_year,
                success_count,
                failure_count,
                source_type,
                document_type
            FROM sources
            WHERE entity_id = ?
            AND covered_metric = ?
            AND (
                -- 优先匹配年份
                covered_year = ?
                -- 或者是通用来源（covered_year 为空）
                OR covered_year IS NULL
            )
            -- 过滤掉近期频繁失败的来源
            AND (
                last_failure IS NULL
                OR last_failure < datetime('now', '-7 days')
                OR failure_count < 3
            )
            {verification_clause}
            ORDER BY
                -- 年份匹配优先
                CASE WHEN covered_year = ? THEN 0 ELSE 1 END,
                -- 可靠性评分降序
                source_reliability_score DESC,
                -- 最近成功时间降序
                last_success DESC
            LIMIT ?
        """

        cursor = self.conn.execute(query, (entity_id, metric, year, year, limit))
        sources = [dict(row) for row in cursor.fetchall()]
        if not sources:
            logger.info("未找到历史来源")
            return []
        logger.info("找到 %d 个历史来源候选", len(sources))
        return sources

    def register_new_source(
        self,
        entity_id: str,
        source_url: str,
        metadata: dict
    ) -> str:
        """注册新来源（Discovery 找到的候选）

        Args:
            entity_id: 电站ID
            source_url: 来源URL
            metadata: {
                "source_type": "official" / "authority" / "search_result",
                "document_type": "pdf" / "html" / "json",
                "covered_metric": "generation" / "capacity",
                "covered_year": 2024,
                "access_method": "http" / "playwright",
                "match_reason": "从官方网站生成",
                "estimated_reliability": 0.8
            }

        Returns:
            source_id: 新创建的来源ID
        """
        source_id = f"src_{uuid.uuid4().hex[:16]}"
        now = now_iso()

        # 初始可靠性评分
        initial_score = metadata.get("estimated_reliability", 0.5)

        self.conn.execute("""
            INSERT INTO sources (
                source_id,
                entity_id,
                entity_type,
                url,
                source_url,
                canonical_url,
                publisher,
                language,
                source_type,
                document_type,
                covered_metric,
                covered_year,
                access_method,
                source_reliability_score,
                match_reason,
                success_count,
                failure_count,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
        """, (
            source_id,
            entity_id,
            "station",  # 默认
            source_url,  # 兼容旧 url 字段
            source_url,
            metadata.get("canonical_url", source_url),
            metadata.get("publisher"),
            metadata.get("language"),
            metadata.get("source_type", "unknown"),
            metadata.get("document_type", "unknown"),
            metadata.get("covered_metric", "generation"),
            metadata.get("covered_year"),
            metadata.get("access_method", "http"),
            initial_score,
            metadata.get("match_reason", ""),
            now,
            now
        ))

        self.conn.commit()
        logger.info(f"注册新来源: {source_id} -> {source_url}")

        return source_id

    def update_success(
        self,
        source_id: str,
        document_id: str = None
    ):
        """更新来源成功记录：提升可靠性评分"""
        now = now_iso()

        self.conn.execute("""
            UPDATE sources
            SET
                last_success = ?,
                success_count = success_count + 1,
                -- 每次成功 +0.05，最高 1.0
                source_reliability_score = MIN(1.0, source_reliability_score + 0.05),
                updated_at = ?
            WHERE source_id = ?
        """, (now, now, source_id))

        # 只在来源已经真实成功后沉淀 Publisher Profile；发现/预检阶段绝不调用。
        try:
            from ..discovery.publisher_profile import PublisherProfileRepository
            PublisherProfileRepository(self.conn).record_success(source_id)
        except sqlite3.OperationalError:
            # v15 未部署的兼容数据库仍可完成来源成功记录。
            pass

        self.conn.commit()

        logger.info(f"来源成功: {source_id} (document_id={document_id})")

    def update_failure(
        self,
        source_id: str,
        reason: str,
        stage: str = "unknown"
    ):
        """更新来源失败记录：降低可靠性评分

        Args:
            source_id: 来源ID
            reason: 失败原因（简短描述）
            stage: 失败阶段（acquisition/parse/extraction）
        """
        now = now_iso()

        self.conn.execute("""
            UPDATE sources
            SET
                last_failure = ?,
                failure_reason = ?,
                failure_count = failure_count + 1,
                -- 每次失败 -0.1，最低 0.0
                source_reliability_score = MAX(0.0, source_reliability_score - 0.1),
                updated_at = ?
            WHERE source_id = ?
        """, (now, f"[{stage}] {reason}", now, source_id))

        self.conn.commit()

        logger.warning(f"来源失败: {source_id} - {reason}")

    def precheck_source(self, source: dict) -> bool:
        """预检查来源是否仍然有效

        简单检查：
        1. 最近是否频繁失败
        2. 上次成功时间是否过久

        Returns:
            True: 来源可用
            False: 来源可能失效，建议重新 Discovery
        """
        # 检查1: 最近7天失败次数
        if source.get("last_failure"):
            try:
                last_failure = datetime.fromisoformat(
                    str(source["last_failure"]).replace("Z", "+00:00")
                )
                now = datetime.now(last_failure.tzinfo) if last_failure.tzinfo else datetime.utcnow()
                days_since_failure = (now - last_failure).days

                if days_since_failure < 7 and source.get("failure_count", 0) >= 3:
                    logger.warning(f"来源 {source['source_id']} 最近频繁失败，建议重新 Discovery")
                    return False
            except (ValueError, TypeError) as e:
                logger.debug(f"解析 last_failure 时间失败: {e}")

        # 检查2: 最近成功时间
        if source.get("last_success"):
            try:
                last_success = datetime.fromisoformat(
                    str(source["last_success"]).replace("Z", "+00:00")
                )
                now = datetime.now(last_success.tzinfo) if last_success.tzinfo else datetime.utcnow()
                days_since_success = (now - last_success).days

                # 超过90天未成功，建议重新检查
                if days_since_success > 90:
                    logger.warning(f"来源 {source['source_id']} 已90天未成功，建议重新验证")
                    return False
            except (ValueError, TypeError) as e:
                logger.debug(f"解析 last_success 时间失败: {e}")

        return True

    def list_sources_for_entity(
        self,
        entity_id: str,
        limit: int = 10
    ) -> List[dict]:
        """列出某个电站的所有历史来源（用于调试和管理）"""
        query = """
            SELECT
                source_id,
                source_url,
                source_type,
                covered_metric,
                covered_year,
                source_reliability_score,
                success_count,
                failure_count,
                last_success,
                last_failure
            FROM sources
            WHERE entity_id = ?
            ORDER BY source_reliability_score DESC, last_success DESC
            LIMIT ?
        """

        cursor = self.conn.execute(query, (entity_id, limit))
        return [dict(row) for row in cursor.fetchall()]
