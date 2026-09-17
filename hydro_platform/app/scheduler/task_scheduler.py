"""自动任务调度器：持续扫描 pending 任务并自动执行（设计文档 §18）。

TaskScheduler 是后台守护进程，每隔一定时间扫描 pending 任务，领取并执行。
支持并发控制、优先级、重试、暂停/恢复。
"""

from __future__ import annotations
import time
import threading
from typing import Callable, Optional, Dict
from datetime import datetime
from pathlib import Path
import sqlite3

from ...common.logging_setup import get_logger
from ...common.enums import FailureStage, TaskStatus
from ...database.connection import connect
from ...database.repositories import TaskRepository
from ...tasking.manager import TaskManager, TaskNotFound
from ...tasking.state_machine import IllegalTransition
from ...intelligence.web_search import SearchRuntime

logger = get_logger(__name__)


class TaskScheduler:
    """自动任务调度器"""

    def __init__(
        self,
        db_path: str,
        task_executor: Callable,  # 执行任务的函数
        max_workers: int = 2,
        scan_interval: int = 5,
        on_task_complete: Callable = None,
        on_task_error: Callable = None,
        search_runtime: SearchRuntime | None = None,
    ):
        """初始化调度器

        Args:
            db_path: 数据库路径
            task_executor: 任务执行函数，签名为 func(task_id) -> result
            max_workers: 最大并发任务数（默认2，避免过载）
            scan_interval: 扫描间隔（秒，默认5秒）
            on_task_complete: 任务完成回调
            on_task_error: 任务错误回调
            search_runtime: 调度器生命周期内共享的搜索运行时；用于跨任务配额和成本统计
        """
        self.db_path = db_path
        self.task_executor = task_executor
        self.max_workers = max_workers
        self.scan_interval = scan_interval
        self.on_task_complete = on_task_complete
        self.on_task_error = on_task_error
        self.search_runtime = search_runtime or SearchRuntime()

        self.running = False
        self.paused = False
        self.scheduler_thread = None

        # Worker 池
        self.active_workers: Dict[str, threading.Thread] = {}
        self.worker_lock = threading.Lock()

    def start(self):
        """启动调度器（后台线程）"""
        if self.running:
            logger.warning("调度器已在运行")
            return

        self.running = True
        self.paused = False

        self.scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="TaskScheduler"
        )
        self.scheduler_thread.start()

        logger.info(f"任务调度器已启动（max_workers={self.max_workers}, scan_interval={self.scan_interval}s）")

    def stop(self):
        """停止调度器"""
        if not self.running:
            return

        logger.info("正在停止任务调度器...")
        self.running = False

        # 等待调度线程退出
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=10)

        # 等待所有 Worker 完成
        with self.worker_lock:
            for task_id, worker_thread in list(self.active_workers.items()):
                logger.info(f"等待任务 {task_id} 完成...")
                worker_thread.join(timeout=30)

        logger.info("任务调度器已停止")

    def pause(self):
        """暂停调度（不影响正在执行的任务）"""
        self.paused = True
        logger.info("任务调度器已暂停")

    def resume(self):
        """恢复调度"""
        self.paused = False
        logger.info("任务调度器已恢复")

    def get_status(self) -> dict:
        """获取调度器状态"""
        with self.worker_lock:
            active_count = len(self.active_workers)

        return {
            "running": self.running,
            "paused": self.paused,
            "active_workers": active_count,
            "max_workers": self.max_workers,
            "scan_interval": self.scan_interval
        }

    def _scheduler_loop(self):
        """调度器主循环（后台线程）"""
        logger.info("调度器主循环开始")

        while self.running:
            try:
                if not self.paused:
                    self._scan_and_dispatch()

                # 清理已完成的 Worker
                self._cleanup_finished_workers()

                # 等待下一次扫描
                time.sleep(self.scan_interval)

            except Exception as e:
                logger.error(f"调度器主循环异常: {e}", exc_info=True)
                time.sleep(self.scan_interval)

        logger.info("调度器主循环结束")

    def _scan_and_dispatch(self):
        """扫描 pending 任务并分发"""
        with self.worker_lock:
            available_slots = self.max_workers - len(self.active_workers)

        if available_slots <= 0:
            # 所有 Worker 都在忙
            return

        # 查询 pending 任务
        conn = connect(Path(self.db_path))
        try:
            task_repo = TaskRepository(conn)
            task_manager = TaskManager(conn)

            # 查询待执行任务（按优先级和创建时间）
            cursor = conn.execute("""
                SELECT task_id, entity_id, task_type, target_period, created_at
                FROM tasks
                WHERE status = ?
                ORDER BY
                    priority_tier ASC,
                    collection_priority ASC,
                    created_at ASC
                LIMIT ?
            """, (TaskStatus.PENDING.value, available_slots))

            pending_tasks = [dict(row) for row in cursor.fetchall()]

            if pending_tasks:
                logger.info(f"扫描到 {len(pending_tasks)} 个 pending 任务，开始分发")

            # 分发任务
            for task_row in pending_tasks:
                task_id = task_row["task_id"]

                # 必须在创建 worker 前原子领取。仅靠 active_workers 只能防住
                # 同一调度器的重复扫描，防不住双启动/多进程调度器竞争。
                try:
                    task_manager.claim(task_id)
                except (TaskNotFound, IllegalTransition):
                    # 另一 worker 已经领取或任务被用户取消，跳过本轮。
                    logger.info("任务 %s 已被其他执行者领取，跳过", task_id)
                    continue

                # 创建 Worker 线程并启动
                try:
                    worker_thread = threading.Thread(
                        target=self._execute_task_wrapper,
                        args=(task_id,),
                        daemon=True,
                        name=f"Worker-{task_id[:8]}"
                    )
                    worker_thread.start()
                except Exception as exc:
                    # 领取成功但线程创建失败时不能留下 running 孤儿。
                    try:
                        task_manager.mark_failed(
                            task_id,
                            failure_stage=FailureStage.UNKNOWN,
                            last_error=f"调度器创建 worker 失败: {exc}",
                        )
                    except Exception:
                        logger.exception("回写 worker 创建失败状态时出错: %s", task_id)
                    logger.error("创建任务 worker 失败: %s", task_id, exc_info=True)
                    continue

                # 记录到活跃 Worker 池
                with self.worker_lock:
                    self.active_workers[task_id] = worker_thread

                logger.info(f"已分发任务: {task_id} (entity_id={task_row['entity_id']}, period={task_row['target_period']})")

        finally:
            conn.close()

    def _execute_task_wrapper(self, task_id: str):
        """任务执行包装器（在 Worker 线程中运行）"""
        try:
            logger.info(f"开始执行任务: {task_id}")
            result = self.task_executor(task_id)
            if isinstance(result, dict) and result.get("status") == "failed":
                self._mark_unfinished_task_failed(task_id, result.get("error"))
            logger.info(f"任务完成: {task_id}")

            # 调用完成回调
            if self.on_task_complete:
                try:
                    self.on_task_complete(task_id, result)
                except Exception as e:
                    logger.error(f"任务完成回调异常: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"任务失败: {task_id} - {e}", exc_info=True)
            self._mark_unfinished_task_failed(task_id, str(e))

            # 调用错误回调
            if self.on_task_error:
                try:
                    self.on_task_error(task_id, {"error": str(e), "error_type": type(e).__name__})
                except Exception as callback_error:
                    logger.error(f"任务错误回调异常: {callback_error}", exc_info=True)

    def _mark_unfinished_task_failed(self, task_id: str, error: str | None) -> None:
        """执行器未能自行落库时，避免已领取任务永久停在 running。"""
        conn = connect(Path(self.db_path))
        try:
            row = conn.execute(
                "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is not None and row["status"] == TaskStatus.RUNNING.value:
                TaskManager(conn).mark_failed(
                    task_id,
                    failure_stage=FailureStage.UNKNOWN,
                    last_error=error or "调度器执行器未返回失败原因",
                )
                conn.commit()
        except (TaskNotFound, IllegalTransition):
            # 正式编排器可能已经把任务落到 failed/needs_review/success。
            pass
        except Exception:
            logger.exception("回写任务失败状态异常: %s", task_id)
        finally:
            conn.close()

    def _cleanup_finished_workers(self):
        """清理已完成的 Worker"""
        with self.worker_lock:
            finished = [
                task_id for task_id, worker_thread in self.active_workers.items()
                if not worker_thread.is_alive()
            ]

            for task_id in finished:
                del self.active_workers[task_id]

            if finished:
                logger.debug(f"清理了 {len(finished)} 个已完成的 Worker")
