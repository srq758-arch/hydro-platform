"""来源与证据领域模型（文档 8 / 14 / 16.3）。

Source：一次采集到的信息来源（URL + 快照 + 元数据）。
Evidence：把某条事实（如 GenerationRecord）与其 Source 及原文定位绑定，
    形成可追溯证据链——任何入库数值都必须能回指到 Source 与原文片段。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from ..common.clock import now_iso


class Source(BaseModel):
    """信息来源。source_id 由 URL + 抓取时间派生（在 repository 层生成/校验）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    url: str
    title: str | None = None
    publisher: str | None = None
    publish_date: str | None = None      # 原文发布日期（ISO 或原文）
    retrieved_at: str | None = None      # 抓取时间（ISO8601 UTC）
    content_hash: str | None = None      # 快照内容哈希，用于变更检测/去重
    archive_path: str | None = None      # 本地快照归档相对路径
    language: str | None = None

    @field_validator("url")
    @classmethod
    def _url_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Source.url 不能为空")
        return v

    def with_retrieved_now(self) -> "Source":
        """补齐 retrieved_at 为当前 UTC（若缺失）。"""
        if self.retrieved_at is None:
            return self.model_copy(update={"retrieved_at": now_iso()})
        return self


class Evidence(BaseModel):
    """证据：事实 <-> 来源 的绑定（文档 14）。

    fact_type/fact_key 指向被支撑的事实（如 generation_record 的 business_key），
    snippet 为原文定位片段，confidence 为抽取置信度。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    evidence_id: str
    source_id: str
    fact_type: str            # 如 "generation_record"
    fact_key: str             # 事实业务键的字符串化
    snippet: str | None = None
    locator: str | None = None    # 页码/表格坐标/CSS 选择器等原文定位
    confidence: float | None = None
    task_id: str | None = None

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence 必须在 [0,1]：{v}")
        return v
