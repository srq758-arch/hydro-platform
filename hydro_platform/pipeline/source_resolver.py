"""数据源解析增强：集成 SourceRegistry 和 Discovery。

优先使用历史来源，无历史来源时触发 Discovery。
"""

from __future__ import annotations
import json
from typing import List
import sqlite3

from ..common.logging_setup import get_logger
from ..common.enums import ContentKind
from ..registry.source_registry import SourceRegistry
from ..models.source_pipeline import CandidateSource
from .source_contract_adapter import (
    normalize_candidate_sources,
    source_task_id,
    to_candidate_source,
)

logger = get_logger(__name__)


def _confirmed_candidate_from_ledger(conn: sqlite3.Connection, task) -> CandidateSource | None:
    """读取用户确认后保存的统一 CandidateSource，保留 SearchLead lineage。"""
    url = str(getattr(task, "user_specified_source", "") or "").strip()
    if not url:
        return None
    task_id = source_task_id(task)
    try:
        row = conn.execute(
            """SELECT candidate_source_id, task_id, lead_id, url, canonical_url, title,
                      publisher, source_type, discovery_method, expected_content_kind,
                      language, priority_score, status, metadata_json, lineage_hash, created_at
               FROM candidate_sources
               WHERE task_id=? AND (url=? OR canonical_url=?)
               ORDER BY created_at DESC LIMIT 1""",
            (task_id, url, url),
        ).fetchone()
    except sqlite3.OperationalError:
        # 正式旧库尚未升级来源契约时沿用兼容 SourceRef 分支。
        return None
    if row is None:
        return None
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    try:
        content_kind = ContentKind(row["expected_content_kind"] or "any")
    except ValueError:
        content_kind = ContentKind.ANY
    return CandidateSource(
        candidate_source_id=row["candidate_source_id"],
        task_id=row["task_id"],
        lead_id=row["lead_id"],
        url=row["url"],
        canonical_url=row["canonical_url"],
        title=row["title"],
        publisher=row["publisher"],
        source_type=row["source_type"],
        discovery_method=row["discovery_method"],
        expected_content_kind=content_kind,
        language=row["language"],
        priority_score=row["priority_score"],
        status=row["status"],
        metadata=metadata,
        lineage_hash=row["lineage_hash"],
        created_at=row["created_at"],
    )


def resolve_sources_enhanced(
    conn: sqlite3.Connection,
    task,
    fallback_resolver=None,
    discovery_resolver: object | None = None,
) -> List[CandidateSource]:
    """增强的来源解析：SourceRegistry → Discovery → Fallback

    Args:
        conn: 数据库连接
        task: 任务对象
        fallback_resolver: 原有的 url_resolver（作为最后手段）

    Returns:
        CandidateSource 列表。旧 SourceReference/SourceRef 只允许作为输入兼容层。

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
        if task.source_type == "intelligent":
            saved = _confirmed_candidate_from_ledger(conn, task)
            if saved is not None:
                return [saved]
        return [to_candidate_source(
            {"url": task.user_specified_source, "source_type": task.source_type},
            task_id=source_task_id(task),
            discovery_method="user_confirmed_url",
            title=label,
            publisher="Intelligent task" if task.source_type == 'intelligent' else "Manual",
        )]

    # PipelineContext 的注入 resolver 是离线测试和受控批处理的明确来源。
    # 它不是全网 Discovery 的回退结果，因此必须先于自动 Discovery 使用，
    # 否则测试或受控任务会意外触发网络请求并被不相关候选覆盖。
    if fallback_resolver:
        try:
            refs = fallback_resolver.resolve(task)
            if refs:
                logger.info("使用注入的受控来源：%d 个", len(refs))
                return normalize_candidate_sources(
                    refs,
                    task_id=source_task_id(task),
                    discovery_method="injected_resolver",
                )
        except Exception as e:
            logger.error(f"注入来源解析失败: {e}", exc_info=True)

    # 准备任务字典（供 Discovery 使用）
    task_dict = {
        "task_id": source_task_id(task),
        "entity_id": task.entity_id,
        "entity_name": getattr(task, "entity_name", None) or _get_entity_name(conn, task.entity_id),
        "target_period": task.target_period,
        "period_type": getattr(task, "period_type", "calendar_year"),
        "metric": "generation"  # 从 task_type 推断
    }

    # Step 1: 查询历史来源。v2 已提供 Registry 所需列；新成功来源也会由
    # orchestrator._register_source 回写 entity/metric/year，使下一次任务可复用。
    registry = SourceRegistry(conn)
    try:
        sources = registry.query_sources(
            entity_id=task.entity_id,
            metric="generation",
            year=int(task.target_period) if task.target_period and task.target_period.isdigit() else None,
            limit=5,
        )
    except sqlite3.OperationalError as exc:
        # Minimal/legacy callers may not have initialized the optional source
        # registry yet. Treat that as "no remembered source" and continue to
        # Discovery rather than crashing source resolution.
        logger.warning("来源注册表不可用，继续 Discovery: %s", exc)
        sources = []

    if sources:
        eligible = [source for source in sources if registry.precheck_source(source)]
        for source in sources:
            if source not in eligible:
                logger.warning("历史来源预检失败: %s", source["source_url"])
        if eligible:
            logger.info("使用 %d 个有效历史来源候选", len(eligible))
            return [
                to_candidate_source(
                    source,
                    task_id=source_task_id(task),
                    discovery_method="source_registry",
                    title=f"历史来源 ({source['source_type']})",
                )
                for source in eligible
            ]

    # Step 3: 触发 Discovery
    logger.info("未找到有效历史来源，开始 Discovery")

    try:
        # 生产默认入口也必须使用 C0 的统一服务，不能在未注入 resolver
        # 时悄悄退回旧 DiscoveryResolver。旧类只保留给历史脚本/兼容调用。
        if discovery_resolver is None:
            from ..intelligence.source_discovery_service import (
                SourceDiscoveryService,
                TaskSourceDiscoveryAdapter,
            )
            resolver = TaskSourceDiscoveryAdapter(SourceDiscoveryService(conn))
        else:
            resolver = discovery_resolver
        candidates = resolver.discover(task_dict, min_candidates=3, max_candidates=5)

        if candidates:
            # 保留评分顺序的候选队列；编排器会在首来源失败后继续尝试后续来源。
            logger.info("Discovery 返回 %d 个候选来源", len(candidates))
            normalized = normalize_candidate_sources(
                candidates,
                task_id=source_task_id(task),
            )
            for candidate in normalized:
                if not candidate.title:
                    candidate.title = f"Discovery ({candidate.source_type})"
            return normalized

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
