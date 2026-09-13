"""Task 生成器（文档 5：Registry → Task）。

把 registry 里的实体展开成采集任务：
  - 电站：每个目标年份一个 station_generation；容量补采一个 station_capacity（无周期）
  - 项目：一个 project_status + 一个 project_commissioning（均无周期）

task_id 由 (entity_id, task_type, target_period) 派生，重复生成幂等——
同一实体同一目标不会产生重复任务（文档 23.1）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from ..common.enums import EntityType, TaskStatus, TaskType
from ..common.logging_setup import get_logger
from ..database.connection import transaction
from ..database.repositories import TaskRepository
from ..models.task import Task

logger = get_logger(__name__)


def _mk_task(
    *,
    entity_id: str,
    entity_type: EntityType,
    task_type: TaskType,
    target_period: str | None,
    priority_tier: str | None,
    collection_priority: int | None,
) -> Task:
    return Task(
        task_id=Task.derive_id(entity_id, task_type, target_period),
        entity_id=entity_id,
        entity_type=entity_type,
        task_type=task_type,
        target_period=target_period,
        status=TaskStatus.PENDING,
        priority_tier=priority_tier,
        collection_priority=collection_priority,
    )


def build_station_tasks(row: sqlite3.Row, *, years: Iterable[int]) -> list[Task]:
    """为单个电站行生成任务：各年份发电量 + 一次容量补采。"""
    eid = row["entity_id"]
    tier = row["priority_tier"]
    prio = row["collection_priority"]
    tasks = [
        _mk_task(
            entity_id=eid,
            entity_type=EntityType.STATION,
            task_type=TaskType.STATION_GENERATION,
            target_period=str(year),
            priority_tier=tier,
            collection_priority=prio,
        )
        for year in years
    ]
    tasks.append(
        _mk_task(
            entity_id=eid,
            entity_type=EntityType.STATION,
            task_type=TaskType.STATION_CAPACITY,
            target_period=None,
            priority_tier=tier,
            collection_priority=prio,
        )
    )
    return tasks


def build_project_tasks(row: sqlite3.Row) -> list[Task]:
    """为单个项目行生成任务：状态跟踪 + 投产时间。"""
    eid = row["entity_id"]
    tier = row["priority_tier"]
    prio = row["collection_priority"]
    return [
        _mk_task(
            entity_id=eid,
            entity_type=EntityType.PROJECT,
            task_type=tt,
            target_period=None,
            priority_tier=tier,
            collection_priority=prio,
        )
        for tt in (TaskType.PROJECT_STATUS, TaskType.PROJECT_COMMISSIONING)
    ]


def generate_from_registry(
    conn: sqlite3.Connection,
    *,
    years: Iterable[int],
    station_limit: int | None = None,
    project_limit: int | None = None,
) -> int:
    """遍历 stations/projects 表生成任务并幂等入库，返回写入任务数。

    years：需要采集发电量的目标年份列表。
    *_limit：仅取前 N 条实体（按 tier + 优先级），用于小规模闭环验证。
    """
    years = list(years)
    repo = TaskRepository(conn)

    st_sql = (
        "SELECT entity_id, priority_tier, collection_priority FROM stations "
        "ORDER BY priority_tier ASC, collection_priority ASC"
    )
    if station_limit is not None:
        st_sql += f" LIMIT {int(station_limit)}"
    pj_sql = (
        "SELECT entity_id, priority_tier, collection_priority FROM projects "
        "ORDER BY priority_tier ASC, collection_priority ASC"
    )
    if project_limit is not None:
        pj_sql += f" LIMIT {int(project_limit)}"

    all_tasks: list[Task] = []
    for row in conn.execute(st_sql):
        all_tasks.extend(build_station_tasks(row, years=years))
    for row in conn.execute(pj_sql):
        all_tasks.extend(build_project_tasks(row))

    with transaction(conn):
        written = repo.upsert_many(all_tasks)

    logger.info(
        "生成任务 %d 条（电站年份 %s，station_limit=%s，project_limit=%s）",
        written, years, station_limit, project_limit,
    )
    return written
