"""Pipeline 统一异常处理（P0-5 修复）。

提供统一的异常包装器，确保：
1. 每个阶段的异常都能正确映射到 FailureStage
2. 任务不会因异常而卡在 running 状态
3. 所有错误信息都能被 task_runs 审计记录
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from ..common.enums import FailureStage
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class PipelineError(Exception):
    """Pipeline 统一异常。

    所有 Pipeline 阶段抛出的异常都应该被包装为此类型，
    以便统一处理和记录。
    """

    def __init__(
        self,
        stage: FailureStage,
        message: str,
        cause: Exception | None = None,
    ):
        self.stage = stage
        self.message = message
        self.cause = cause
        super().__init__(message)

    def __str__(self) -> str:
        if self.cause:
            return f"{self.stage.value}: {self.message} (caused by {type(self.cause).__name__}: {self.cause})"
        return f"{self.stage.value}: {self.message}"


def wrap_stage(stage: FailureStage) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """阶段执行装饰器。

    将函数内的任何异常包装为 PipelineError，并标记失败阶段。

    用法：
        @wrap_stage(FailureStage.ACQUISITION_FAILED)
        def acquire_data(ctx, url):
            # ... 采集逻辑 ...

    如果函数内抛出任何异常，会被捕获并包装为：
        PipelineError(stage=ACQUISITION_FAILED, message="...", cause=原始异常)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except PipelineError:
                # 已经是 Pipeline 错误，直接上抛
                raise
            except Exception as e:
                # 包装为 Pipeline 错误
                logger.error(
                    f"Stage {stage.value} failed in {func.__name__}: {e}",
                    exc_info=True,
                )
                raise PipelineError(
                    stage=stage,
                    message=f"{func.__name__} failed: {str(e)}",
                    cause=e,
                ) from e

        return wrapper

    return decorator


def safe_execute(
    stage: FailureStage,
    func: Callable[..., T],
    *args,
    **kwargs,
) -> T:
    """安全执行函数，捕获异常并包装为 PipelineError。

    用于不方便使用装饰器的场景，如动态调用或 lambda。

    用法：
        result = safe_execute(
            FailureStage.PARSE_FAILED,
            parse_document,
            doc_id,
            content_type="html"
        )
    """
    try:
        return func(*args, **kwargs)
    except PipelineError:
        raise
    except Exception as e:
        logger.error(f"Stage {stage.value} failed: {e}", exc_info=True)
        raise PipelineError(
            stage=stage,
            message=f"Execution failed: {str(e)}",
            cause=e,
        ) from e
