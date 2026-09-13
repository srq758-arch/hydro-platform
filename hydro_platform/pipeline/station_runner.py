"""单座电站闭环驱动（文档 §25「先完成单任务闭环」）。

给定一座电站的 entity_id 与目标年份，生成其发电量任务并逐个跑过管线，
返回每个任务的 PipelineResult。这是「单座电站真实闭环」的顶层入口。
"""

from __future__ import annotations

from ..common.enums import EntityType, TaskStatus, TaskType
from ..common.logging_setup import get_logger
from ..database.repositories import TaskRepository
from ..models.task import Task
from ..tasking.builder import build_station_tasks
from .context import PipelineContext
from .orchestrator import run_task
from .result import PipelineResult

logger = get_logger(__name__)


def run_station(
    ctx: PipelineContext,
    entity_id: str,
    *,
    years: list[int],
) -> list[PipelineResult]:
    """为一座电站生成发电量任务并逐一跑过管线。任务先幂等入库。"""
    row = ctx.conn.execute(
        "SELECT entity_id, priority_tier, collection_priority FROM stations "
        "WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"stations 中无 entity_id={entity_id}")

    tasks = build_station_tasks(row, years=years)
    # 只保留发电量采集任务（容量类任务不走本管线）
    gen_tasks = [t for t in tasks if t.task_type == TaskType.STATION_GENERATION]

    repo = TaskRepository(ctx.conn)
    from ..database.connection import transaction

    with transaction(ctx.conn):
        repo.upsert_many(gen_tasks)

    results: list[PipelineResult] = []
    for task in gen_tasks:
        # 重新取库中当前状态：已 success 的幂等跳过（可续跑）
        cur = repo.get(task.task_id)
        if cur is not None and cur["status"] == TaskStatus.SUCCESS.value:
            logger.info("任务 %s 已 success，幂等跳过", task.task_id)
            continue
        results.append(run_task(ctx, task))
    return results
