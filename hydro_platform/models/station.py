"""存量电站领域模型（文档 3.1 / 16.1）。

Station 对应 GEM 存量水电站。字段以 build_seed_list.py 实际输出列为准，
只做结构定义与字段级校验，不含持久化逻辑。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..common.enums import EntityType


class Station(BaseModel):
    """存量水电站。entity_id 为全局唯一主键（来自 seed 的 entity_id）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    entity_id: str
    entity_type: EntityType = EntityType.STATION
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
    status: str | None = None
    technology: str | None = None
    operator: str | None = None
    owner: str | None = None
    commissioning_year: int | None = None
    retired_year: int | None = None

    # GEM 溯源标识
    gem_location_id: str | None = None
    gem_unit_id: str | None = None
    gem_wiki_url: str | None = None

    # 优先级与流程状态（来自 seed，可被后续管线更新）
    priority_tier: str | None = None
    collection_priority: int | None = None
    needs_review: bool = False

    # 溯源与版本
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
