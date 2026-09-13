"""LLM 结构化输出 schema（文档 12.2「必须输出符合 Pydantic Schema 的候选」）。

LLM 只允许返回符合此 schema 的 JSON，字段全部可空——识别不出就留空，禁止编造
（文档 13.3 不能猜测补齐）。转换成领域 ExtractionCandidate 时统一打 extractor=llm-*。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...common.enums import MeasurementScope, PeriodType, ValueType
from ...models.candidate import ExtractionCandidate

LLM_EXTRACTOR_VERSION = "llm-v1"


class LLMCandidate(BaseModel):
    """LLM 抽出的单条候选（严格 schema，拒绝多余字段）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    period_label: str | None = None
    period_type: PeriodType | None = None
    generation_gwh: float | None = None
    value_type: ValueType | None = None
    measurement_scope: MeasurementScope | None = None
    value_raw: str | None = None
    unit_raw: str | None = None
    snippet: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("generation_gwh")
    @classmethod
    def _non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError(f"generation_gwh 不能为负：{v}")
        return v

    def to_candidate(
        self,
        *,
        entity_id: str | None = None,
        task_id: str | None = None,
        source_id: str | None = None,
        locator: str | None = None,
    ) -> ExtractionCandidate:
        """转成领域候选。打 extractor=llm-v1 与 LLM_SOURCED 标记以便区分来源。"""
        flags = ["LLM_SOURCED"]
        if self.value_type == ValueType.FORECAST:
            flags.append("FORECAST_SUSPECT")
        if self.measurement_scope in (MeasurementScope.REGION, MeasurementScope.COMPLEX):
            flags.append("SCOPE_NOT_PLANT")
        return ExtractionCandidate(
            entity_id=entity_id,
            period_type=self.period_type,
            period_label=self.period_label,
            generation_gwh=self.generation_gwh,
            value_type=self.value_type,
            measurement_scope=self.measurement_scope,
            value_raw=self.value_raw,
            unit_raw=self.unit_raw,
            snippet=self.snippet,
            locator=locator,
            confidence=self.confidence,
            extractor=LLM_EXTRACTOR_VERSION,
            task_id=task_id,
            source_id=source_id,
            flags=flags,
        )


class LLMExtractionOutput(BaseModel):
    """LLM 一次抽取的完整输出：候选列表。"""

    model_config = ConfigDict(extra="forbid")

    candidates: list[LLMCandidate] = Field(default_factory=list)
