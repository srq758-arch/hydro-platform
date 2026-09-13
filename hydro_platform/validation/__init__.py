"""Validation 层（文档 13）。

三层校验：Common（格式/单位/必填）→ Master（电站身份/发电量/容量-发电量/年份/
actual-forecast）→ Project（项目状态/生命周期/日期）。统一返回 ValidationResult，
禁止只返回 True/False（文档 13.2）。铁律：不能靠猜测补齐缺失数据，
「没有公开数据 ≠ 发电量为 0」（文档 13.3）——generation_gwh=NULL 是允许的。
"""

from __future__ import annotations

from .engine import (
    ValidationContext,
    validate_candidate,
    validate_project_record,
)

__all__ = [
    "ValidationContext",
    "validate_candidate",
    "validate_project_record",
]
