"""解析分发（文档 11）。

按内容类型把原始字节路由到对应解析器。content_kind 未知时按魔数/内容再探测一次
（复用 acquisition.validators.detect_content_kind），仍未知则返回 ok=False。
parse_document 从归档的本地文件读取字节后解析，衔接 Archive → Parse 顺序。
"""

from __future__ import annotations

from pathlib import Path

from ..common.enums import ContentKind
from ..common.logging_setup import get_logger
from ..acquisition.validators import detect_content_kind
from .content import ParsedContent
from .html_parser import parse_html
from .json_parser import parse_json
from .pdf_parser import parse_pdf
from .table_parser import parse_csv, parse_excel

logger = get_logger(__name__)


def parse_bytes(body: bytes, kind: ContentKind, *, content_type: str | None = None) -> ParsedContent:
    """按 kind 解析字节。kind 为 UNKNOWN/ANY 时按内容重探测。"""
    if kind in (ContentKind.UNKNOWN, ContentKind.ANY):
        kind = detect_content_kind(body, content_type)

    if kind == ContentKind.HTML:
        return parse_html(body)
    if kind == ContentKind.JSON:
        return parse_json(body)
    if kind == ContentKind.CSV:
        return parse_csv(body)
    if kind == ContentKind.EXCEL:
        return parse_excel(body)
    if kind == ContentKind.PDF:
        return parse_pdf(body)
    return ParsedContent.unavailable(kind, f"不支持的内容类型：{kind}")


def parse_document(local_path: str | Path, kind: ContentKind, *, content_type: str | None = None) -> ParsedContent:
    """读取归档的本地文件并解析（衔接 Archive → Parse）。"""
    path = Path(local_path)
    try:
        body = path.read_bytes()
    except OSError as exc:
        return ParsedContent.unavailable(kind, f"读取归档文件失败 {path}：{exc}")
    return parse_bytes(body, kind, content_type=content_type)
