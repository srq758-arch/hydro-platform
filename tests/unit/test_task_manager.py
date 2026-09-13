"""任务管理器单测：状态语义方法、非法转换拒绝、重试上限与复核结论。"""

from __future__ import annotations

import pytest

from hydro_platform.common.enums import (
    EntityType,
    FailureStage,
    TaskStatus,
    TaskType,
)
from hydro_platform.database.repositories import TaskRepository
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
