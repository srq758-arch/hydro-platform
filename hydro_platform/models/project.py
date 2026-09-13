"""新增项目领域模型（文档 3.2 / 16.1）。

Project 对应在建/新投产/规划中的水电项目。与 Station 共享 seed 列结构，
额外承载项目状态语义（under_construction / newly_commissioned 等）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from ..common.enums import EntityType


class Project(BaseModel):
    """新增水电项目。entity_id 为全局唯一主键（来自 seed 的 entity_id）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    entity_id: str
    entity_type: EntityType = EntityType.PROJECT
    canonical_name: str
    aliases: str | None = None
    local_name: str | None = None

    country: str | None = None
    country_2: str | None = None
    region: str | None = None
    subregion: str | None = None
    state_province: str | None = None
    river: str | None = None

    latitude: float | None = None
    longitude: float | None = None
    location_accuracy: str | None = None

    capacity_mw: float | None = None
    turbines: int | None = None
    # status 保留 seed 原始字符串；语义化状态由后续管线归一到 ProjectStatus
    status: str | None = None
    technology: str | None = None
    operator: str | None = None
    owner: str | None = None
    commissioning_year: int | None = None

    gem_location_id: str | None = None
    gem_unit_id: str | None = None
    gem_wiki_url: str | None = None

    priority_tier: str | None = None
    collection_priority: int | None = None
    needs_review: bool = False

    source_seed: str | None = None
    source_url: str | None = None
    dataset_version: str | None = None
    registry_version: str | None = None
    raw_record_hash: str | None = None

    @field_validator("latitude")
    @classmethod
    def _lat_range(cls, v: float | None) -> float | None:
        if v is not None and not (-90.0 <= v <= 90.0):
            raise ValueError(f"latitude 越界：{v}")
        return v

    @field_validator("longitude")
    @classmethod
    def _lon_range(cls, v: float | None) -> float | None:
        if v is not None and not (-180.0 <= v <= 180.0):
            raise ValueError(f"longitude 越界：{v}")
        return v

    @field_validator("capacity_mw")
    @classmethod
    def _capacity_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError(f"capacity_mw 不能为负：{v}")
        return v
