"""任务领域模型（文档 5）。

Task 是整个系统的调度单元：一个实体的一类采集目标（如某电站某年发电量）。
状态流转规则集中在 tasking.state_machine，本模型只承载数据与派生逻辑。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..common.clock import now_iso
from ..common.enums import EntityType, FailureStage, TaskStatus, TaskType


class Task(BaseModel):
    """采集任务。

    task_id 由 (entity_id, task_type, target_period) 派生，保证同一目标只生成一个任务
    （幂等，文档 23.1）。attempts 记录重试次数，failure_stage 记录最近失败分类。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    task_id: str
    entity_id: str
    entity_type: EntityType
    task_type: TaskType
    target_period: str | None = None      # 如 "2024"；容量类任务可为空

    status: TaskStatus = TaskStatus.PENDING
    priority_tier: str | None = None
    collection_priority: int | None = None

    attempts: int = 0
    max_attempts: int = 3
    failure_stage: FailureStage | None = None
    last_error: str | None = None

    # D01/D10: 来源跟踪字段
    source_type: str = "automatic"  # manual | automatic
    user_specified_source: str | None = None  # 用户指定的URL或文件路径

    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @field_validator("max_attempts")
    @classmethod
    def _max_attempts_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_attempts 必须 >=1：{v}")
        return v

    @property
    def is_terminal(self) -> bool:
        """是否处于终态（不再调度）。"""
        return self.status in (
            TaskStatus.SUCCESS,
            TaskStatus.CANCELLED,
        )

    @property
    def can_retry(self) -> bool:
        """失败后是否还可重试。"""
        return self.status == TaskStatus.FAILED and self.attempts < self.max_attempts

    @staticmethod
    def derive_id(entity_id: str, task_type: TaskType, target_period: str | None) -> str:
        """派生稳定 task_id。相同三元组恒定产出同一 id（幂等键）。"""
        period = target_period or "-"
        return f"{entity_id}::{task_type.value}::{period}"
