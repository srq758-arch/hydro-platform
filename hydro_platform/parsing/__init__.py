"""Parsing 内容解析层（文档 11）。

只回答「文件里有什么文字、表格和结构」，不判断业务含义（是否目标电站/实际发电量/
目标年份等交给 Extraction/Validation/Review）。支持 HTML/PDF/Excel/CSV/JSON。

重依赖（pypdf/openpyxl）延迟导入；未安装时对应格式返回不可用的 ParsedContent，
不抛异常、不崩溃（文档约定的优雅降级）。
"""

from .content import ParsedContent, Table
from .html_parser import parse_html
from .json_parser import parse_json
from .table_parser import parse_csv, parse_excel
from .pdf_parser import parse_pdf, pdf_available
from .pdf_renderer import (
    PdfRenderError,
    PdfRenderUnavailable,
    RenderedPdfPage,
    pdf_render_available,
    render_pdf_pages,
)
from .pdf_ocr import (
    OcrPageText,
    OcrRegion,
    PdfOcrError,
    PdfOcrUnavailable,
    PytesseractBackend,
    ocr_available,
    ocr_environment_report,
    ocr_rendered_pages,
)
from .dispatcher import parse_document, parse_bytes

__all__ = [
    "ParsedContent",
    "Table",
    "parse_html",
    "parse_json",
    "parse_csv",
    "parse_excel",
    "parse_pdf",
    "pdf_available",
    "PdfRenderError",
    "PdfRenderUnavailable",
    "RenderedPdfPage",
    "pdf_render_available",
    "render_pdf_pages",
    "OcrPageText",
    "OcrRegion",
    "PdfOcrError",
    "PdfOcrUnavailable",
    "PytesseractBackend",
    "ocr_available",
    "ocr_environment_report",
    "ocr_rendered_pages",
    "parse_document",
    "parse_bytes",
]
