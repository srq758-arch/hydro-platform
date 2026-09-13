"""管线运行结果类型（文档 §22 步骤 14）。

StageOutcome 记录管线跑到哪个阶段、结论如何；PipelineResult 汇总一个任务的
最终状态与产物计数，供调用方/测试断言与审计。诚实反映失败——不吞异常。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..common.enums import FailureStage, TaskStatus


@dataclass
class StageOutcome:
    """单阶段结论。"""

    stage: str
    ok: bool
    detail: str | None = None


@dataclass
class PipelineResult:
    """一个任务端到端运行的结果。"""

    task_id: str
    final_status: TaskStatus
    reached_stage: str
    stages: list[StageOutcome] = field(default_factory=list)
    failure_stage: FailureStage | None = None

    documents_archived: int = 0
    candidates_extracted: int = 0
    candidates_promoted: int = 0
    review_ids: list[str] = field(default_factory=list)
    promoted_keys: list[dict] = field(default_factory=list)
    error: str | None = None

    def record(self, stage: str, ok: bool, detail: str | None = None) -> None:
        self.stages.append(StageOutcome(stage, ok, detail))
        self.reached_stage = stage

    @property
    def needs_review(self) -> bool:
        return self.final_status == TaskStatus.NEEDS_REVIEW

    @property
    def succeeded(self) -> bool:
        return self.final_status == TaskStatus.SUCCESS
