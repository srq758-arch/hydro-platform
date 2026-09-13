"""发电量记录领域模型（文档 5.1 / 16.2）。

GenerationRecord 是系统的核心事实表：某实体在某周期的发电量。
value_type / measurement_scope 是防伪造关键字段（文档 12.3）：
必须显式区分「实际 vs 预测」「单站 vs 区域合计」，否则一律进人工复核。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from ..common.enums import MeasurementScope, PeriodType, ValueType


class GenerationRecord(BaseModel):
    """单条发电量事实。

    (entity_id, period_type, period_label, value_type, measurement_scope) 共同
    构成业务唯一键，对应数据库 UNIQUE 约束（文档 16.4），保证重复采集不重复入库。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    entity_id: str
    period_type: PeriodType = PeriodType.CALENDAR_YEAR
    period_label: str  # 如 "2024"、"2024-Q1"
    generation_gwh: float

    value_type: ValueType = ValueType.ACTUAL
    measurement_scope: MeasurementScope = MeasurementScope.PLANT

    unit_raw: str | None = None       # 原文单位（如 "亿千瓦时"），保留以便追溯换算
    value_raw: str | None = None      # 原文数值字符串
    source_id: str | None = None      # 关联 Source.source_id（证据链）
    task_id: str | None = None        # 产出该记录的任务

    @field_validator("generation_gwh")
    @classmethod
    def _generation_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"generation_gwh 不能为负：{v}")
        return v

    @field_validator("period_label")
    @classmethod
    def _period_label_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("period_label 不能为空")
        return v

    def business_key(self) -> tuple[str, str, str, str, str]:
        """返回业务唯一键元组，供去重/幂等 upsert 使用。"""
        return (
            self.entity_id,
            self.period_type.value,
            self.period_label,
            self.value_type.value,
            self.measurement_scope.value,
        )
