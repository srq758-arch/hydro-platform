"""数据源解析增强：集成 SourceRegistry 和 Discovery。

优先使用历史来源，无历史来源时触发 Discovery。
"""

from __future__ import annotations
from typing import List, Optional
import sqlite3

from ..common.logging_setup import get_logger
from ..common.enums import ContentKind
from ..registry.source_registry import SourceRegistry
from ..discovery.resolver import DiscoveryResolver

logger = get_logger(__name__)


class SourceReference:
    """来源引用（兼容原有 url_resolver 返回格式）"""
    def __init__(
        self,
        url: str,
        title: str = None,
        publisher: str = None,
        expected: ContentKind = ContentKind.ANY,
        language: str = None
    ):
        self.url = url
        self.title = title
        self.publisher = publisher
        self.expected = expected
        self.language = language


def resolve_sources_enhanced(
    conn: sqlite3.Connection,
    task,
    fallback_resolver=None,
    discovery_resolver: DiscoveryResolver | None = None,
) -> List[SourceReference]:
    """增强的来源解析：SourceRegistry → Discovery → Fallback

    Args:
        conn: 数据库连接
        task: 任务对象
        fallback_resolver: 原有的 url_resolver（作为最后手段）

    Returns:
        SourceReference 列表

    流程：
    D01修复：如果任务是用户手动指定来源(source_type='manual')，直接返回用户指定的来源，跳过自动搜索
    1. 查询 SourceRegistry 历史来源
    2. 如果找到且预检通过 → 返回
    3. 如果没有历史来源 → 触发 Discovery
    4. Discovery 返回排序候选 → 返回 Top 1
    5. 如果 Discovery 也失败 → 尝试 fallback_resolver
    """
    logger.info(f"开始解析数据源: entity_id={task.entity_id}, period={task.target_period}")

    # D01修复：用户手动指定的来源不被自动搜索替换
    if getattr(task, 'source_type', None) in {'manual', 'intelligent'} and getattr(task, 'user_specified_source', None):
        label = "智能任务已确认来源" if task.source_type == 'intelligent' else "用户指定来源"
        logger.info(f"使用{label}（不触发自动搜索）: {task.user_specified_source}")
        return [SourceReference(
            url=task.user_specified_source,
            title=label,
            publisher="Intelligent task" if task.source_type == 'intelligent' else "Manual",
            # 已确认 URL 的实际载体可能是 PDF、HTML、Excel 或 CSV。
            # "unknown" 不是宽松类型，而会被下载校验当成强制类型，导致任何
            # 实际文档都被误判为 NOT_EXPECTED_TYPE；此处应允许路由器自主识别。
            expected=ContentKind.ANY,
        )]

    # PipelineContext 的注入 resolver 是离线测试和受控批处理的明确来源。
    # 它不是全网 Discovery 的回退结果，因此必须先于自动 Discovery 使用，
    # 否则测试或受控任务会意外触发网络请求并被不相关候选覆盖。
    if fallback_resolver:
        try:
            refs = fallback_resolver.resolve(task)
            if refs:
                logger.info("使用注入的受控来源：%d 个", len(refs))
                return refs
        except Exception as e:
            logger.error(f"注入来源解析失败: {e}", exc_info=True)

    # 准备任务字典（供 Discovery 使用）
    task_dict = {
        "entity_id": task.entity_id,
        "entity_name": getattr(task, "entity_name", None) or _get_entity_name(conn, task.entity_id),
        "target_period": task.target_period,
        "metric": "generation"  # 从 task_type 推断
    }

    # Step 1: 查询历史来源。v2 已提供 Registry 所需列；新成功来源也会由
    # orchestrator._register_source 回写 entity/metric/year，使下一次任务可复用。
    registry = SourceRegistry(conn)
    source = registry.query_best_source(
        entity_id=task.entity_id,
        metric="generation",
        year=int(task.target_period) if task.target_period and task.target_period.isdigit() else None,
    )

    if source:
        # Step 2: 预检查
        if registry.precheck_source(source):
            logger.info(f"使用历史来源: {source['source_url']} (评分: {source['source_reliability_score']:.2f})")
            return [SourceReference(
                url=source["source_url"],
                title=f"历史来源 ({source['source_type']})",
                # 注册表的 document_type 是历史线索，不是下载约束：来源可能
                # 重定向、改版或使用不准确的响应头，交由采集器按实际内容识别。
                expected=ContentKind.ANY,
            )]
        else:
            logger.warning(f"历史来源预检失败: {source['source_url']}")

    # Step 3: 触发 Discovery
    logger.info("未找到有效历史来源，开始 Discovery")

    try:
        resolver = discovery_resolver or DiscoveryResolver(conn)
        candidates = resolver.discover(task_dict, min_candidates=3, max_candidates=5)

        if candidates:
            # 保留评分顺序的候选队列；编排器会在首来源失败后继续尝试后续来源。
            logger.info("Discovery 返回 %d 个候选来源", len(candidates))
            return [
                SourceReference(
                    url=item["url"],
                    title=f"Discovery ({item.get('source_type', 'unknown')})",
                    # Discovery 的 document_type 是 URL/LLM 推测，尤其 unknown
                    # 不能被当作“只能下载 unknown 文件”的强制条件。
                    expected=ContentKind.ANY,
                )
                for item in candidates
            ]

    except Exception as e:
        logger.error(f"Discovery 失败: {e}", exc_info=True)

    # 全部失败
    logger.error("所有来源解析方法均失败")
    return []


def _get_entity_name(conn: sqlite3.Connection, entity_id: str) -> str:
    """从数据库获取电站名称"""
    cursor = conn.execute(
        "SELECT canonical_name FROM stations WHERE entity_id = ?",
        (entity_id,)
    )
    row = cursor.fetchone()
    return row["canonical_name"] if row else entity_id
