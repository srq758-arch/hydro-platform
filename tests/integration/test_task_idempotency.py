"""任务创建不得覆盖运行态和来源审计。"""

from hydro_platform.common.enums import EntityType, TaskStatus, TaskType
from hydro_platform.models.task import Task
from hydro_platform.database.repositories import TaskRepository


def _task(task_id: str, *, status=TaskStatus.PENDING, source_type="automatic", source=None):
    return Task(
        task_id=task_id,
        entity_id="station_idempotent",
        entity_type=EntityType.STATION,
        task_type=TaskType.STATION_GENERATION,
        target_period="2024",
        status=status,
        attempts=2,
        max_attempts=3,
        source_type=source_type,
        user_specified_source=source,
    )


def test_duplicate_task_upsert_preserves_runtime_and_manual_source(db):
    repo = TaskRepository(db)
    original = _task(
        "station_idempotent::station_generation::2024",
        status=TaskStatus.SUCCESS,
        source_type="manual",
        source="file:///frozen/report.pdf",
    )
    repo.upsert_many([original])
    db.execute(
        "UPDATE tasks SET attempts=3, failure_stage='UNKNOWN', last_error='audit' "
        "WHERE task_id=?",
        (original.task_id,),
    )
    db.commit()

    # 普通任务构建器产生的默认值不能冲掉已完成任务或用户来源。
    repo.upsert_many([_task(original.task_id)])
    row = repo.get(original.task_id)

    assert row["status"] == TaskStatus.SUCCESS.value
    assert row["attempts"] == 3
    assert row["failure_stage"] == "UNKNOWN"
    assert row["last_error"] == "audit"
    assert row["source_type"] == "manual"
    assert row["user_specified_source"] == "file:///frozen/report.pdf"
