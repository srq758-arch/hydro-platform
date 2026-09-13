"""Pipeline Orchestrator（文档 §22 步骤 14 / §25「单任务闭环」）。

把九层串成端到端可跑管线：tasking → acquisition → archive → parsing →
extraction → validation → evidence → review-gate →（人工断点）→ promotion。

铁律（文档 §15）：Top100 相关记录必须人工复核——全自动管线对 Top100 永远停在
Review Queue，由 apply_review_decision 在人工 approve 后才升级。未复核数据不进 Top100。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .context import PipelineContext, SourceRef
from .result import PipelineResult, StageOutcome

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查，避免 review ↔ pipeline 循环导入
    from .orchestrator import apply_review_decision, run_task

__all__ = [
    "PipelineContext",
    "SourceRef",
    "PipelineResult",
    "StageOutcome",
    "run_task",
    "apply_review_decision",
]


def __getattr__(name: str):
    """延迟加载编排器导出，保持轻量 pipeline 子模块可独立导入。"""
    if name in {"run_task", "apply_review_decision"}:
        from .orchestrator import apply_review_decision, run_task

        return {
            "run_task": run_task,
            "apply_review_decision": apply_review_decision,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
