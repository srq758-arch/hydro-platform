"""PDF 解析（文档 11）——pypdf 可选依赖，延迟导入。

抽取每页文本并汇总。pypdf 未安装时返回 ok=False（不崩溃），供上层降级或转人工。
表格/版面/OCR 是后续增强项，本期只做文本层。
"""

from __future__ import annotations

import importlib.util
import io

from ..common.enums import ContentKind
from .content import ParsedContent


def pdf_available() -> bool:
    """pypdf 是否已安装（不解析，仅探测）。"""
    return importlib.util.find_spec("pypdf") is not None


def parse_pdf(body: bytes) -> ParsedContent:
    """解析 PDF 文本层。缺 pypdf 则 ok=False。"""
    if not pdf_available():
        return ParsedContent.unavailable(
            ContentKind.PDF, "未安装 pypdf，无法解析 PDF（pip install .[parsing]）"
        )
    from pypdf import PdfReader  # 延迟导入
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(body))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except (PdfReadError, Exception) as exc:  # noqa: BLE001 - 损坏 PDF 不致命
        return ParsedContent.unavailable(ContentKind.PDF, f"PDF 解析失败：{exc}")

    text = "\n".join(pages).strip()
    return ParsedContent(
        kind=ContentKind.PDF,
        ok=True,
        text=text,
        meta={"n_pages": len(pages)},
    )
