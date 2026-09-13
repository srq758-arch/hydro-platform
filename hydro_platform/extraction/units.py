"""发电量单位识别与归一（文档 12.3 防 MW↔GWh 混淆）。

关键区分：
- 功率单位（MW/GW/kW）是「容量」，绝不能当作「发电量」——识别到功率单位时
  归一失败并打标记，交由校验层判 CAPACITY_GENERATION_CONFLICT。
- 电量单位（Wh 系）统一归一到 GWh。中文「亿千瓦时」= 1e8 kWh = 1e5 MWh = 100 GWh。

只做单位换算，不判断数值是否合理（那是 Validation 的事）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 电量单位 → 换算到 GWh 的系数
_ENERGY_TO_GWH = {
    "kwh": 1e-6,
    "mwh": 1e-3,
    "gwh": 1.0,
    "twh": 1e3,
    "亿千瓦时": 100.0,      # 1 亿 kWh = 1e8 kWh = 100 GWh
    "亿度": 100.0,           # 度 = kWh
    "万千瓦时": 1e-2,        # 1 万 kWh = 1e4 kWh = 0.01 GWh
    "万度": 1e-2,
    "度": 1e-6,              # 1 度 = 1 kWh
    "千瓦时": 1e-6,
    "兆瓦时": 1e-3,
}

# 功率（容量）单位——不是发电量，标记冲突
_POWER_UNITS = {"kw", "mw", "gw", "千瓦", "兆瓦", "万千瓦"}


@dataclass
class UnitParse:
    """单位解析结果。

    is_energy=True 且 factor_to_gwh 非空表示可归一到 GWh；is_power=True 表示识别到
    功率单位（容量），归一无意义、应作冲突处理；两者皆 False 表示单位不明。
    """

    raw: str | None
    is_energy: bool = False
    is_power: bool = False
    factor_to_gwh: float | None = None
    canonical: str | None = None


def parse_unit(unit_text: str | None) -> UnitParse:
    """识别单位文本类别。大小写/空白不敏感，兼容中英文。"""
    if not unit_text:
        return UnitParse(raw=unit_text)
    t = unit_text.strip().lower().replace(" ", "")
    # 中文电量单位（原样匹配，含"亿千瓦时"等多字词）
    for key, factor in _ENERGY_TO_GWH.items():
        if key.isascii():
            continue
        if key in unit_text:
            return UnitParse(raw=unit_text, is_energy=True, factor_to_gwh=factor, canonical=key)
    # 英文电量单位
    for key, factor in _ENERGY_TO_GWH.items():
        if not key.isascii():
            continue
        if re.fullmatch(rf"{key}", t) or t == key:
            return UnitParse(raw=unit_text, is_energy=True, factor_to_gwh=factor, canonical=key)
    # 功率单位（容量），中英文
    for key in _POWER_UNITS:
        if key.isascii():
            if re.fullmatch(rf"{key}", t):
                return UnitParse(raw=unit_text, is_power=True, canonical=key)
        elif key in unit_text:
            return UnitParse(raw=unit_text, is_power=True, canonical=key)
    return UnitParse(raw=unit_text)


def normalize_to_gwh(value: float, unit_text: str | None) -> tuple[float | None, UnitParse]:
    """把 value 按单位归一到 GWh。

    返回 (gwh_or_None, UnitParse)。功率单位或单位不明时返回 None（不猜测），
    由调用方据 UnitParse 打相应标记。
    """
    up = parse_unit(unit_text)
    if up.is_energy and up.factor_to_gwh is not None:
        return value * up.factor_to_gwh, up
    return None, up
