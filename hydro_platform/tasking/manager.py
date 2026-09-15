"""任务管理器（文档 5.3：执行状态转换 + 持久化）。

manager 是状态转换的唯一执行入口：每次转换都先读当前状态、经 state_machine
校验合法性，再落库。上层（worker、review）只调用语义方法（claim/mark_*），
不直接写 status，避免状态漂移。
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from ..common.clock import now
from ..common.enums import FailureStage, TaskStatus
from ..common.logging_setup import get_logger
from ..database.connection import transaction
from ..database.repositories import TaskRepository
from . import state_machine as sm

logger = get_logger(__name__)


class TaskNotFound(LookupError):
    """按 task_id 未找到任务。"""


class TaskManager:
    """封装任务状态流转。所有转换走 state_machine 校验后持久化。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = TaskRepository(conn)

    # ---- 内部 ----

    def _current_status(self, task_id: str) -> TaskStatus:
        row = self.repo.get(task_id)
        if row is None:
            raise TaskNotFound(task_id)
        return TaskStatus(row["status"])

    def _transition(
        self,
        task_id: str,
        dst: TaskStatus,
        *,
        failure_stage: FailureStage | None = None,
        last_error: str | None = None,
        bump_attempt: bool = False,
    ) -> None:
        src = self._current_status(task_id)
        sm.assert_transition(src, dst)
        with transaction(self.conn):
            self.repo.update_status(
                task_id,
                dst.value,
                failure_stage=failure_stage.value if failure_stage else None,
                last_error=last_error,
                bump_attempt=bump_attempt,
            )
        logger.debug("任务 %s：%s → %s", task_id, src.value, dst.value)

    # ---- 语义方法 ----

    def claim(
        self,
        task_id: str,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 120,
    ) -> None:
        """调度器原子领取任务：pending → running。

        不能先读再写，否则两个 scheduler 可能同时观察到 pending 并重复执行。
        条件 UPDATE 在 SQLite 写锁内重新判断状态，竞争者只有一个能成功。
        """
        if lease_seconds < 1:
            raise ValueError("lease_seconds 必须 >= 1")
        claimed_at = now()
        expires_at = (claimed_at + timedelta(seconds=lease_seconds)).isoformat()
        with transaction(self.conn):
            if self.repo.claim_if_pending(
                task_id,
                worker_id=worker_id,
                lease_expires_at=expires_at if worker_id else None,
                heartbeat_at=claimed_at.isoformat() if worker_id else None,
            ):
                logger.debug("任务 %s：pending → running（原子领取）", task_id)
                return
            row = self.repo.get(task_id)
            if row is None:
                raise TaskNotFound(task_id)
            raise sm.IllegalTransition(TaskStatus(row["status"]), TaskStatus.RUNNING)

    def heartbeat(self, task_id: str, *, worker_id: str, lease_seconds: int = 120) -> bool:
        """续期当前 worker 的租约；失去租约时返回 False，不覆盖其他 worker。"""
        if not worker_id:
            raise ValueError("worker_id 不能为空")
        if lease_seconds < 1:
            raise ValueError("lease_seconds 必须 >= 1")
        heartbeat_at = now()
        with transaction(self.conn):
            return self.repo.heartbeat_lease(
                task_id,
                worker_id=worker_id,
                heartbeat_at=heartbeat_at.isoformat(),
                lease_expires_at=(heartbeat_at + timedelta(seconds=lease_seconds)).isoformat(),
            )

    def recover_expired_leases(self) -> list[str]:
        """恢复崩溃 worker 遗留任务为 failed，随后须经既有重试上限再回排。"""
        with transaction(self.conn):
            return self.repo.recover_expired_leases(before=now().isoformat())

    def mark_success(self, task_id: str) -> None:
        """采集入库成功：running → success。清空失败痕迹。"""
        self._transition(task_id, TaskStatus.SUCCESS, failure_stage=None, last_error=None)

    def mark_failed(
        self,
        task_id: str,
        *,
        failure_stage: FailureStage,
        last_error: str | None = None,
    ) -> None:
        """采集失败：running → failed，attempts +1，记录失败阶段。"""
        self._transition(
            task_id,
            TaskStatus.FAILED,
            failure_stage=failure_stage,
            last_error=last_error,
            bump_attempt=True,
        )

    def mark_needs_review(self, task_id: str, *, last_error: str | None = None) -> None:
        """产出需人工复核：running → needs_review。"""
        self._transition(task_id, TaskStatus.NEEDS_REVIEW, last_error=last_error)

    def cancel(self, task_id: str) -> None:
        """取消任务（可从 pending/running/failed/needs_review 进入终态）。"""
        self._transition(task_id, TaskStatus.CANCELLED)

    def cancel_many(self, task_ids: list[str]) -> list[str]:
        """原子取消一组任务，返回实际取消的任务 ID。

        批量清理测试任务不能出现“前半批已取消、后半批因状态非法失败”的
        部分结果，因此先完整校验全部状态，再在一个事务中统一落库。
        """
        unique_ids = list(dict.fromkeys(task_ids))
        if not unique_ids:
            return []
        rows = {task_id: self.repo.get(task_id) for task_id in unique_ids}
        missing = [task_id for task_id, row in rows.items() if row is None]
        if missing:
            raise TaskNotFound(", ".join(missing))
        for task_id, row in rows.items():
            sm.assert_transition(row["status"], TaskStatus.CANCELLED)
        with transaction(self.conn):
            for task_id in unique_ids:
                self.repo.update_status(task_id, TaskStatus.CANCELLED.value)
        logger.debug("批量取消 %d 个任务", len(unique_ids))
        return unique_ids

    def requeue(self, task_id: str) -> bool:
        """失败重试：failed → pending。超过 max_attempts 则不重排，返回 False。"""
        row = self.repo.get(task_id)
        if row is None:
            raise TaskNotFound(task_id)
        if row["status"] != TaskStatus.FAILED.value:
            raise sm.IllegalTransition(TaskStatus(row["status"]), TaskStatus.PENDING)
        if row["attempts"] >= row["max_attempts"]:
            logger.info(
                "任务 %s 已达最大重试次数 %d，不再重排", task_id, row["max_attempts"]
            )
            return False
        self._transition(task_id, TaskStatus.PENDING)
        return True

    def reopen_cancelled_for_explicit_source(self, task_id: str) -> bool:
        """用户显式提交新来源时，将已取消任务开启为一个新的执行轮次。

        ``cancelled`` 通常是终态，不能被调度器或普通重试自动恢复；但用户在
        桌面端重新提交已绑定电站、年份和 URL 的来源时，这是一个明确的新意图。
        仅在该受控入口下清除旧失败痕迹并回到 pending。
        """
        row = self.repo.get(task_id)
        if row is None:
            raise TaskNotFound(task_id)
        if row["status"] != TaskStatus.CANCELLED.value:
            return False
        with transaction(self.conn):
            self.repo.update_status(
                task_id,
                TaskStatus.PENDING.value,
                failure_stage=None,
                last_error=None,
            )
        logger.info("用户显式来源重新开启已取消任务: %s", task_id)
        return True

    def reopen_failed_for_open_review(self, task_id: str) -> bool:
        """仍有 open 复核项时，将历史失败任务恢复到复核断点。

        旧实现会在同一任务的第一条候选被拒绝后立刻标记整个任务失败，
        从而阻断其余候选的人工裁决。仅由复核 API 调用此方法，恢复的
        前提是调用方已确认存在未决复核项。
        """
        row = self.repo.get(task_id)
        if row is None:
            raise TaskNotFound(task_id)
        if row["status"] != TaskStatus.FAILED.value:
            return False
        with transaction(self.conn):
            self.repo.update_status(
                task_id,
                TaskStatus.NEEDS_REVIEW.value,
                failure_stage=None,
                last_error=None,
            )
        logger.info("为未决复核恢复失败任务: %s", task_id)
        return True

    # ---- 复核结论 ----

    def approve(self, task_id: str) -> None:
        """人工通过：needs_review → success。"""
        self._transition(task_id, TaskStatus.SUCCESS, failure_stage=None, last_error=None)

    def reject(self, task_id: str, *, last_error: str | None = None) -> None:
        """人工驳回：needs_review → failed。"""
        self._transition(
            task_id,
            TaskStatus.FAILED,
            failure_stage=FailureStage.REVIEW_REJECTED,
            last_error=last_error,
            bump_attempt=True,
        )
