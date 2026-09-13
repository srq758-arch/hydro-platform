"""抽取候选模型（文档 12）。

ExtractionCandidate 是 Extraction 层的产物——尚未经 Validation/Evidence/Review 的
「候选事实」，绝不等于正式 GenerationRecord（文档 12.2「LLM 输出 ≠ 正式事实」，
规则抽取同理）。候选保留原文线索（value_raw/unit_raw/snippet）与识别到的
period/value_type/scope，供校验层判定七类混淆风险（文档 12.3）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..common.enums import MeasurementScope, PeriodType, ValueType


class ExtractionCandidate(BaseModel):
    """一条候选发电量事实。字段可空——识别不出就留空，禁止猜测补齐（文档 13.3）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    # 持久化层的不可变候选版本标识。抽取器不负责生成它；管线在已取得
    # document_id 后按候选内容确定性生成，避免重跑产生新的候选版本。
    candidate_id: str | None = None
    entity_id: str | None = None
    period_type: PeriodType | None = None
    period_label: str | None = None          # 如 "2024"、"2024-Q1"
    generation_gwh: float | None = None      # 已归一到 GWh 的值（可空）

    value_type: ValueType | None = None
    measurement_scope: MeasurementScope | None = None

    value_raw: str | None = None             # 原文数值字符串
    unit_raw: str | None = None              # 原文单位（如 "亿千瓦时"）
    snippet: str | None = None               # 原文定位片段（证据用）
    locator: str | None = None               # 页码/表格坐标/选择器

    confidence: float | None = None          # 抽取置信度 [0,1]
    extractor: str | None = None             # 产出该候选的抽取器名（规则名/llm）
    task_id: str | None = None
    source_id: str | None = None

    # 抽取器未决但需人工留意的线索（如"单位不明""疑似区域合计"）
    flags: list[str] = Field(default_factory=list)
