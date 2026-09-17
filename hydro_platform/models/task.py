"""任务领域模型（文档 5）。

Task 是整个系统的调度单元：一个实体的一类采集目标（如某电站某年发电量）。
状态流转规则集中在 tasking.state_machine，本模型只承载数据与派生逻辑。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..common.clock import now_iso
from ..common.enums import EntityType, FailureStage, PeriodType, TaskStatus, TaskType


class Task(BaseModel):
    """采集任务。

    task_id 由 (entity_id, task_type, target_period, period_type) 派生，保证同一
    目标和统计口径只生成一个任务（幂等，文档 23.1）。自然年沿用历史 ID，
    财政年度追加口径后缀以保持旧任务可寻址。attempts 记录重试次数，
    failure_stage 记录最近失败分类。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    task_id: str
    entity_id: str
    entity_type: EntityType
    task_type: TaskType
    target_period: str | None = None      # 如 "2024"；容量类任务可为空
    period_type: PeriodType = PeriodType.CALENDAR_YEAR

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

    @field_validator("task_type", mode="before")
    @classmethod
    def _normalize_legacy_task_type(cls, v: TaskType | str) -> TaskType | str:
        """把 v1 早期别名归一化到统一任务类型。

        旧 tasks 行可能保存 ``generation_annual``。如果不在领域模型入口
        统一处理，CLI/API/调度器会出现不同的兼容行为，且旧任务无法重建。
        """
        if str(v) == "generation_annual":
            return TaskType.STATION_GENERATION
        return v

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
    def derive_id(
        entity_id: str, task_type: TaskType, target_period: str | None,
        period_type: PeriodType | str = PeriodType.CALENDAR_YEAR,
    ) -> str:
        """派生稳定 task_id。

        日历年沿用旧 ID，避免历史任务失联；财政年度追加口径，避免把同一
        年份的财年任务误当成已经完成的自然年任务。
        """
        period = target_period or "-"
        kind = period_type.value if isinstance(period_type, PeriodType) else str(period_type or "calendar_year")
        suffix = "" if kind == PeriodType.CALENDAR_YEAR.value else f"::{kind}"
        return f"{entity_id}::{task_type.value}::{period}{suffix}"
