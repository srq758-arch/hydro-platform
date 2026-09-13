"""Simple Worker：后台线程执行任务，通过回调报告进度。

符合文档第 18 节要求：
- 在后台线程执行一个 Task
- 通过回调或事件报告进度
- 报告完成结果
- 报告错误
- 支持取消标记
- 不阻塞 GUI 主线程
"""

import threading
from typing import Callable, Optional, Any
from dataclasses import dataclass


@dataclass
class WorkerEvent:
    """Worker 事件：进度更新、状态变化、完成或错误。"""
    event_type: str  # progress, state_change, complete, error
    task_id: str
    message: str
    data: Optional[dict] = None


class SimpleWorker:
    """最简后台 Worker：单任务、非阻塞、可取消。"""

    def __init__(self, task_id: str, callback: Callable[[WorkerEvent], None]):
        """
        Args:
            task_id: 任务唯一 ID
            callback: 事件回调函数，接收 WorkerEvent
        """
        self.task_id = task_id
        self.callback = callback
        self._thread: Optional[threading.Thread] = None
        self._cancel_flag = threading.Event()
        self._running = False

    def start(self, target_func: Callable[[], Any], *args, **kwargs) -> None:
        """启动后台任务。

        Args:
            target_func: 要执行的任务函数
            *args, **kwargs: 传递给 target_func 的参数
        """
        if self._running:
            raise RuntimeError(f"Worker {self.task_id} 已经在运行")

        def _wrapped_target():
            self._running = True
            try:
                result = target_func(*args, **kwargs)
                if not self._cancel_flag.is_set():
                    self.callback(WorkerEvent(
                        event_type="complete",
                        task_id=self.task_id,
                        message="任务完成",
                        data={"result": result}
                    ))
            except Exception as e:
                if not self._cancel_flag.is_set():
                    self.callback(WorkerEvent(
                        event_type="error",
                        task_id=self.task_id,
                        message=f"任务失败：{str(e)}",
                        data={"error": str(e), "error_type": type(e).__name__}
                    ))
            finally:
                self._running = False

        self._thread = threading.Thread(target=_wrapped_target, daemon=True)
        self._thread.start()

    def report_progress(self, message: str, data: Optional[dict] = None) -> None:
        """报告进度（由任务函数内部调用）。"""
        if not self._cancel_flag.is_set():
            self.callback(WorkerEvent(
                event_type="progress",
                task_id=self.task_id,
                message=message,
                data=data
            ))

    def report_state_change(self, message: str, data: Optional[dict] = None) -> None:
        """报告状态变化（由任务函数内部调用）。"""
        if not self._cancel_flag.is_set():
            self.callback(WorkerEvent(
                event_type="state_change",
                task_id=self.task_id,
                message=message,
                data=data
            ))

    def cancel(self) -> None:
        """请求取消任务（设置取消标记，由任务函数检查）。"""
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        """检查是否已被请求取消（任务函数内定期检查）。"""
        return self._cancel_flag.is_set()

    def is_running(self) -> bool:
        """检查任务是否正在运行。"""
        return self._running

    def join(self, timeout: Optional[float] = None) -> bool:
        """等待任务完成。

        Args:
            timeout: 超时秒数，None 表示无限等待

        Returns:
            True 如果任务已完成，False 如果超时
        """
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()
