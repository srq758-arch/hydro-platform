"""审批事务原子性保证（D08修复）。

确保复核决策的所有状态更新（review_items、generation_records、tasks）
要么全部成功，要么全部回滚，避免出现不一致状态。

问题场景：
1. 审批失败但 review_items 已标记 approve
2. generation_records 已发布但 validation 失败
3. task 状态与实际结果不一致

解决方案：
- 使用 SQLite 事务保证原子性
- 明确定义状态边界和回滚点
- 失败时恢复到一致的中间状态
"""

from __future__ import annotations
from typing import Optional, Callable, Any
from contextlib import contextmanager
import sqlite3

from ..common.logging_setup import get_logger
from ..common.enums import TaskStatus, FailureStage
from ..common.clock import now_iso

logger = get_logger(__name__)


class ApprovalTransaction:
    """审批事务管理器。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._savepoint_count = 0

    @contextmanager
    def atomic_approval(self, review_id: str, task_id: str):
        """原子性审批上下文管理器。

        使用方式:
            with transaction.atomic_approval(review_id, task_id) as tx:
                tx.mark_review_approved(review_id)
                tx.promote_to_generation_records(...)
                tx.mark_task_success(task_id)
                # 所有操作成功后自动提交
                # 任何异常都会回滚

        Args:
            review_id: 复核项ID
            task_id: 任务ID

        Yields:
            TransactionContext: 事务上下文
        """
        savepoint_name = f"approval_{self._savepoint_count}"
        self._savepoint_count += 1

        try:
            # 开始事务（如果还没有开始）
            self.conn.execute(f"SAVEPOINT {savepoint_name}")
            logger.debug(f"开始审批事务: {review_id}, savepoint={savepoint_name}")

            # 创建事务上下文
            ctx = TransactionContext(self.conn, review_id, task_id, savepoint_name)

            yield ctx

            # 成功：提交
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            self.conn.commit()
            logger.info(f"审批事务成功提交: {review_id}")

        except Exception as e:
            # 失败：回滚到 savepoint
            logger.error(f"审批事务失败，回滚: {review_id}, 原因: {e}")
            try:
                self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                self.conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            except Exception as rollback_err:
                logger.error(f"回滚失败: {rollback_err}")
            raise


class TransactionContext:
    """事务操作上下文。"""

    def __init__(self, conn: sqlite3.Connection, review_id: str, task_id: str, savepoint: str):
        self.conn = conn
        self.review_id = review_id
        self.task_id = task_id
        self.savepoint = savepoint
        self._operations = []

    def mark_review_approved(self, reviewer: str):
        """标记复核项为已批准。

        Args:
            reviewer: 审核人
        """
        self.conn.execute("""
            UPDATE review_items
            SET status = 'approve',
                reviewer = ?,
                resolved_at = ?
            WHERE review_id = ?
        """, (reviewer, now_iso(), self.review_id))

        self._operations.append(f"mark_review_approved({self.review_id})")
        logger.debug(f"[{self.savepoint}] 标记复核项已批准: {self.review_id}")

    def mark_review_rejected(self, reviewer: str, reason: Optional[str] = None):
        """标记复核项为已拒绝。

        Args:
            reviewer: 审核人
            reason: 拒绝原因
        """
        self.conn.execute("""
            UPDATE review_items
            SET status = 'reject',
                reviewer = ?,
                resolved_value = ?,
                resolved_at = ?
            WHERE review_id = ?
        """, (reviewer, reason, now_iso(), self.review_id))

        self._operations.append(f"mark_review_rejected({self.review_id})")
        logger.debug(f"[{self.savepoint}] 标记复核项已拒绝: {self.review_id}")

    def mark_review_needs_evidence(self, reviewer: str):
        """标记复核项需要补充证据。

        Args:
            reviewer: 审核人
        """
        self.conn.execute("""
            UPDATE review_items
            SET status = 'request_more_evidence',
                reviewer = ?,
                resolved_at = ?
            WHERE review_id = ?
        """, (reviewer, now_iso(), self.review_id))

        self._operations.append(f"mark_review_needs_evidence({self.review_id})")
        logger.debug(f"[{self.savepoint}] 标记复核项需要补充证据: {self.review_id}")

    def promote_to_generation_records(
        self,
        entity_id: str,
        period_label: str,
        generation_gwh: float,
        evidence_id: str,
        **kwargs
    ) -> int:
        """将候选升级为正式发电量记录。

        Args:
            entity_id: 实体ID
            period_label: 期间标签
            generation_gwh: 发电量
            evidence_id: 证据ID
            **kwargs: 其他字段

        Returns:
            插入的记录ID
        """
        # V5.2-A：该遗留事务没有 Candidate/Validation/审批版本上下文，禁止
        # 直接写正式表。保留方法只为让陈旧调用以可诊断错误失败。
        raise RuntimeError(
            "ApprovalTransaction 直写入口已禁用；请通过 orchestrator 审批并由 "
            "lifecycle.promotion.promote_candidate 正式写入"
        )

    def mark_task_success(self):
        """标记任务为成功。"""
        self.conn.execute("""
            UPDATE tasks
            SET status = 'success',
                updated_at = ?
            WHERE task_id = ?
        """, (now_iso(), self.task_id))

        self._operations.append(f"mark_task_success({self.task_id})")
        logger.debug(f"[{self.savepoint}] 标记任务成功: {self.task_id}")

    def mark_task_failed(self, failure_stage: FailureStage, error: str):
        """标记任务为失败。

        Args:
            failure_stage: 失败阶段
            error: 错误信息
        """
        self.conn.execute("""
            UPDATE tasks
            SET status = 'failed',
                failure_stage = ?,
                last_error = ?,
                updated_at = ?
            WHERE task_id = ?
        """, (failure_stage.value, error, now_iso(), self.task_id))

        self._operations.append(f"mark_task_failed({self.task_id}, {failure_stage.value})")
        logger.debug(f"[{self.savepoint}] 标记任务失败: {self.task_id}, {failure_stage.value}")

    def mark_task_needs_review(self):
        """标记任务为需要复核。"""
        self.conn.execute("""
            UPDATE tasks
            SET status = 'needs_review',
                updated_at = ?
            WHERE task_id = ?
        """, (now_iso(), self.task_id))

        self._operations.append(f"mark_task_needs_review({self.task_id})")
        logger.debug(f"[{self.savepoint}] 标记任务需要复核: {self.task_id}")

    def get_operations_summary(self) -> str:
        """获取已执行的操作摘要。

        Returns:
            操作摘要字符串
        """
        return " -> ".join(self._operations)
