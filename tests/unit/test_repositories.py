"""Repository upsert 幂等性单测（不依赖 seed 文件）。"""

from __future__ import annotations

from hydro_platform.common.enums import EntityType, TaskStatus, TaskType
from hydro_platform.database.repositories import (
    StationRepository,
    TaskRepository,
)
from hydro_platform.models.station import Station
from hydro_platform.models.task import Task


def _station(entity_id: str, name: str) -> Station:
    return Station(entity_id=entity_id, canonical_name=name)


def test_station_upsert_is_idempotent(db):
    repo = StationRepository(db)
    repo.upsert_many([_station("s1", "Alpha"), _station("s2", "Beta")])
    db.commit()
    assert repo.count() == 2
    # 重复 upsert 相同主键：行数不变，字段被覆盖
    repo.upsert_many([_station("s1", "Alpha v2")])
    db.commit()
    assert repo.count() == 2
    assert repo.get("s1")["canonical_name"] == "Alpha v2"


def test_task_upsert_preserves_created_at(db):
    repo = TaskRepository(db)
    tid = Task.derive_id("s1", TaskType.STATION_GENERATION, "2024")
    t = Task(
        task_id=tid,
        entity_id="s1",
        entity_type=EntityType.STATION,
        task_type=TaskType.STATION_GENERATION,
        target_period="2024",
        created_at="2020-01-01T00:00:00+00:00",
        updated_at="2020-01-01T00:00:00+00:00",
    )
    repo.upsert_many([t])
    db.commit()
    original_created = repo.fetch_by_status(TaskStatus.PENDING.value)[0]["created_at"]

    # 重新 upsert（updated_at 变化）：created_at 必须保留首次值
    t2 = t.model_copy(update={"updated_at": "2099-12-31T00:00:00+00:00"})
    repo.upsert_many([t2])
    db.commit()
    row = repo.fetch_by_status(TaskStatus.PENDING.value)[0]
    assert repo.count() == 1
    assert row["created_at"] == original_created
    assert row["updated_at"] == "2099-12-31T00:00:00+00:00"


def test_update_status_bumps_attempt(db):
    repo = TaskRepository(db)
    tid = Task.derive_id("s1", TaskType.STATION_GENERATION, "2024")
    repo.upsert_many([
        Task(
            task_id=tid,
            entity_id="s1",
            entity_type=EntityType.STATION,
            task_type=TaskType.STATION_GENERATION,
            target_period="2024",
        )
    ])
    db.commit()
    repo.update_status(tid, TaskStatus.FAILED.value, failure_stage="PARSE_FAILED", bump_attempt=True)
    db.commit()
    row = repo.fetch_by_status(TaskStatus.FAILED.value)[0]
    assert row["attempts"] == 1
    assert row["failure_stage"] == "PARSE_FAILED"
