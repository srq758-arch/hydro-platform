"""任务管理器单测：状态语义方法、非法转换拒绝、重试上限与复核结论。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from hydro_platform.common.enums import (
    EntityType,
    FailureStage,
    TaskStatus,
    TaskType,
)
from hydro_platform.database.repositories import TaskRepository
from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import migrate
from hydro_platform.models.task import Task
from hydro_platform.tasking.manager import TaskManager, TaskNotFound
from hydro_platform.tasking.state_machine import IllegalTransition


def _make_task(db, *, max_attempts: int = 3) -> str:
    repo = TaskRepository(db)
    tid = Task.derive_id("s1", TaskType.STATION_GENERATION, "2024")
    repo.upsert_many([
        Task(
            task_id=tid,
            entity_id="s1",
            entity_type=EntityType.STATION,
            task_type=TaskType.STATION_GENERATION,
            target_period="2024",
            max_attempts=max_attempts,
        )
    ])
    db.commit()
    return tid


def _status(db, tid: str) -> str:
    return TaskRepository(db).get(tid)["status"]


def test_claim_and_success(db):
    tid = _make_task(db)
    mgr = TaskManager(db)
    mgr.claim(tid)
    assert _status(db, tid) == TaskStatus.RUNNING.value
    mgr.mark_success(tid)
    row = TaskRepository(db).get(tid)
    assert row["status"] == TaskStatus.SUCCESS.value
    assert row["failure_stage"] is None
    assert row["last_error"] is None


def test_mark_failed_bumps_attempt(db):
    tid = _make_task(db)
    mgr = TaskManager(db)
    mgr.claim(tid)
    mgr.mark_failed(tid, failure_stage=FailureStage.PARSE_FAILED, last_error="boom")
    row = TaskRepository(db).get(tid)
    assert row["status"] == TaskStatus.FAILED.value
    assert row["attempts"] == 1
    assert row["failure_stage"] == FailureStage.PARSE_FAILED.value
    assert row["last_error"] == "boom"


def test_needs_review_and_approve(db):
    tid = _make_task(db)
    mgr = TaskManager(db)
    mgr.claim(tid)
    mgr.mark_needs_review(tid, last_error="uncertain")
    assert _status(db, tid) == TaskStatus.NEEDS_REVIEW.value
    mgr.approve(tid)
    assert _status(db, tid) == TaskStatus.SUCCESS.value


def test_needs_review_and_reject(db):
    tid = _make_task(db)
    mgr = TaskManager(db)
    mgr.claim(tid)
    mgr.mark_needs_review(tid)
    mgr.reject(tid, last_error="wrong number")
    row = TaskRepository(db).get(tid)
    assert row["status"] == TaskStatus.FAILED.value
    assert row["failure_stage"] == FailureStage.REVIEW_REJECTED.value
    assert row["attempts"] == 1


def test_cancel_from_pending(db):
    tid = _make_task(db)
    mgr = TaskManager(db)
    mgr.cancel(tid)
    assert _status(db, tid) == TaskStatus.CANCELLED.value


def test_illegal_transition_rejected(db):
    tid = _make_task(db)
    mgr = TaskManager(db)
    # pending → success 非法
    with pytest.raises(IllegalTransition):
        mgr.mark_success(tid)
    # 状态未被改动
    assert _status(db, tid) == TaskStatus.PENDING.value


def test_requeue_success(db):
    tid = _make_task(db, max_attempts=3)
    mgr = TaskManager(db)
    mgr.claim(tid)
    mgr.mark_failed(tid, failure_stage=FailureStage.PARSE_FAILED)
    assert TaskRepository(db).get(tid)["attempts"] == 1
    assert mgr.requeue(tid) is True
    assert _status(db, tid) == TaskStatus.PENDING.value


def test_requeue_hits_retry_cap(db):
    tid = _make_task(db, max_attempts=2)
    mgr = TaskManager(db)
    # 两轮失败使 attempts 达到 max_attempts
    mgr.claim(tid)
    mgr.mark_failed(tid, failure_stage=FailureStage.PARSE_FAILED)
    assert mgr.requeue(tid) is True
    mgr.claim(tid)
    mgr.mark_failed(tid, failure_stage=FailureStage.PARSE_FAILED)
    row = TaskRepository(db).get(tid)
    assert row["attempts"] == 2
    # attempts >= max_attempts → 不再重排
    assert mgr.requeue(tid) is False
    assert _status(db, tid) == TaskStatus.FAILED.value


def test_requeue_rejects_non_failed(db):
    tid = _make_task(db)
    mgr = TaskManager(db)
    # pending 状态不能 requeue
    with pytest.raises(IllegalTransition):
        mgr.requeue(tid)


def test_task_not_found(db):
    mgr = TaskManager(db)
    with pytest.raises(TaskNotFound):
        mgr.claim("does-not-exist")
    with pytest.raises(TaskNotFound):
        mgr.requeue("does-not-exist")


def test_competing_connections_only_one_can_claim(tmp_path):
    """两个独立 SQLite 连接真实竞争同一任务，不允许重复领取或锁异常。"""
    db_path = tmp_path / "claim-race.db"
    setup = connect(db_path, timeout=5.0)
    migrate(setup)
    setup.execute(
        "INSERT INTO stations(entity_id, entity_type, canonical_name) VALUES ('s1', 'station', 'S1')"
    )
    task_id = _make_task(setup)
    setup.close()

    def claim_once():
        conn = connect(db_path, timeout=5.0)
        try:
            TaskManager(conn).claim(task_id)
            return "claimed"
        except IllegalTransition:
            return "lost"
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim_once(), range(2)))

    assert sorted(outcomes) == ["claimed", "lost"]
    check = connect(db_path, read_only=True)
    try:
        assert TaskRepository(check).get(task_id)["status"] == TaskStatus.RUNNING.value
    finally:
        check.close()


def test_worker_lease_heartbeat_and_terminal_transition_clear_claim(db):
    tid = _make_task(db)
    manager = TaskManager(db)

    manager.claim(tid, worker_id="worker-alpha", lease_seconds=60)
    claimed = TaskRepository(db).get(tid)
    assert claimed["worker_id"] == "worker-alpha"
    assert claimed["lease_expires_at"]
    assert claimed["heartbeat_at"]
    assert manager.heartbeat(tid, worker_id="worker-alpha", lease_seconds=60) is True
    assert manager.heartbeat(tid, worker_id="worker-beta", lease_seconds=60) is False

    manager.mark_success(tid)
    finished = TaskRepository(db).get(tid)
    assert finished["status"] == TaskStatus.SUCCESS.value
    assert finished["worker_id"] is None
    assert finished["lease_expires_at"] is None
    assert finished["heartbeat_at"] is None


def test_expired_lease_becomes_retryable_failure_without_overwriting_fresh_claim(db):
    expired_id = _make_task(db)
    fresh_id = Task.derive_id("s2", TaskType.STATION_GENERATION, "2024")
    db.execute(
        "INSERT INTO stations(entity_id, entity_type, canonical_name) VALUES ('s2', 'station', 'S2')"
    )
    TaskRepository(db).upsert_many([
        Task(
            task_id=fresh_id,
            entity_id="s2",
            entity_type=EntityType.STATION,
            task_type=TaskType.STATION_GENERATION,
            target_period="2024",
        )
    ])
    db.commit()
    manager = TaskManager(db)
    manager.claim(expired_id, worker_id="expired-worker")
    manager.claim(fresh_id, worker_id="fresh-worker")
    db.execute(
        "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE task_id=?",
        (expired_id,),
    )
    db.commit()

    assert manager.recover_expired_leases() == [expired_id]
    expired = TaskRepository(db).get(expired_id)
    fresh = TaskRepository(db).get(fresh_id)
    assert expired["status"] == TaskStatus.FAILED.value
    assert expired["attempts"] == 1
    assert expired["worker_id"] is None
    assert fresh["status"] == TaskStatus.RUNNING.value
    assert fresh["worker_id"] == "fresh-worker"
    assert manager.requeue(expired_id) is True
