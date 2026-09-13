"""任务生成器单测：逐实体任务生成 + 从 registry 批量生成的幂等性/LIMIT。"""

from __future__ import annotations

from hydro_platform.common.enums import TaskType
from hydro_platform.database.repositories import (
    ProjectRepository,
    StationRepository,
    TaskRepository,
)
from hydro_platform.models.project import Project
from hydro_platform.models.station import Station
from hydro_platform.tasking.builder import (
    build_project_tasks,
    build_station_tasks,
    generate_from_registry,
)

YEARS = [2022, 2023, 2024]


def _station_row(entity_id: str = "s1") -> dict:
    return {
        "entity_id": entity_id,
        "priority_tier": "T1",
        "collection_priority": 10,
    }


def _project_row(entity_id: str = "p1") -> dict:
    return {
        "entity_id": entity_id,
        "priority_tier": "T2",
        "collection_priority": 20,
    }


def test_build_station_tasks_generation_and_capacity():
    tasks = build_station_tasks(_station_row("s1"), years=YEARS)
    gen = [t for t in tasks if t.task_type == TaskType.STATION_GENERATION]
    cap = [t for t in tasks if t.task_type == TaskType.STATION_CAPACITY]

    # 每年一个发电量任务
    assert len(gen) == len(YEARS)
    assert {t.target_period for t in gen} == {"2022", "2023", "2024"}
    # 容量任务恰一个，且无期间
    assert len(cap) == 1
    assert cap[0].target_period is None

    # 优先级透传
    for t in tasks:
        assert t.entity_id == "s1"
        assert t.priority_tier == "T1"
        assert t.collection_priority == 10
    # id 唯一
    assert len({t.task_id for t in tasks}) == len(tasks)


def test_build_project_tasks_status_and_commissioning():
    tasks = build_project_tasks(_project_row("p1"))
    types = {t.task_type for t in tasks}
    assert types == {TaskType.PROJECT_STATUS, TaskType.PROJECT_COMMISSIONING}
    assert all(t.target_period is None for t in tasks)
    assert all(t.entity_id == "p1" for t in tasks)
    assert len({t.task_id for t in tasks}) == 2


def _seed_registry(db, n_stations: int, n_projects: int) -> None:
    st = StationRepository(db)
    pj = ProjectRepository(db)
    st.upsert_many([
        Station(
            entity_id=f"s{i}",
            canonical_name=f"Station {i}",
            priority_tier="T1",
            collection_priority=i,
        )
        for i in range(n_stations)
    ])
    pj.upsert_many([
        Project(
            entity_id=f"p{i}",
            canonical_name=f"Project {i}",
            priority_tier="T2",
            collection_priority=i,
        )
        for i in range(n_projects)
    ])
    db.commit()


def test_generate_from_registry_counts_and_idempotent(db):
    _seed_registry(db, n_stations=2, n_projects=2)
    repo = TaskRepository(db)

    written = generate_from_registry(db, years=YEARS)
    # 每站: len(YEARS) 发电量 + 1 容量 = 4；两站 = 8
    # 每项目: 2；两项目 = 4 → 合计 12
    per_station = len(YEARS) + 1
    per_project = 2
    expected = 2 * per_station + 2 * per_project
    assert written == expected
    assert repo.count() == expected

    # 再跑一遍：幂等，总数不变
    generate_from_registry(db, years=YEARS)
    assert repo.count() == expected


def test_generate_from_registry_honors_limits(db):
    _seed_registry(db, n_stations=5, n_projects=5)
    repo = TaskRepository(db)

    generate_from_registry(db, years=YEARS, station_limit=1, project_limit=1)
    per_station = len(YEARS) + 1
    per_project = 2
    assert repo.count() == per_station + per_project
