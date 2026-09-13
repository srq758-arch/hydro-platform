"""解析产物统一类型（文档 11）。

ParsedContent 是所有解析器的统一输出：正文文本 + 表格 + 结构化字段（如标题、
链接、JSON 对象）。不承载任何业务判断。ok=False + error 表示解析失败/不可用
（如缺少可选依赖），供上层决定是否降级或转人工。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..common.enums import ContentKind


@dataclass
class Table:
    """一张二维表。headers 可空（无表头时）；rows 为字符串化单元格。"""

    rows: list[list[str]] = field(default_factory=list)
    headers: list[str] | None = None
    caption: str | None = None

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        if self.headers:
            return len(self.headers)
        return max((len(r) for r in self.rows), default=0)


@dataclass
class ParsedContent:
    """统一解析结果。"""

    kind: ContentKind
    ok: bool = True
    text: str = ""
    tables: list[Table] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    title: str | None = None
    data: Any = None          # JSON 解析出的原生对象等
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def unavailable(cls, kind: ContentKind, reason: str) -> "ParsedContent":
        """解析不可用（缺依赖/不支持），返回 ok=False 而非抛异常。"""
        return cls(kind=kind, ok=False, error=reason)

    def __bool__(self) -> bool:
        return self.ok
