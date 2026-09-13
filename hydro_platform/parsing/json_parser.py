"""JSON/API 解析（文档 11）——标准库 json。

保留原生对象到 data，并把顶层可读文本汇入 text 便于规则抽取粗扫。
不判断业务含义。
"""

from __future__ import annotations

import json

from ..common.enums import ContentKind
from .content import ParsedContent


def parse_json(body: bytes | str, *, encoding: str = "utf-8") -> ParsedContent:
    """解析 JSON。非法 JSON 返回 ok=False（不抛异常）。"""
    raw = body.decode(encoding, errors="ignore") if isinstance(body, bytes) else body
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return ParsedContent.unavailable(ContentKind.JSON, f"JSON 解析失败：{exc}")
    return ParsedContent(
        kind=ContentKind.JSON,
        ok=True,
        text=raw,
        data=obj,
    )
