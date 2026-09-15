"""PDF 页面渲染基础设施（D4）。

渲染只负责把原始 PDF 页转换为可复核的 PNG，不负责 OCR、不猜测字段，也不
直接写正式数据。PyMuPDF 是可选依赖；缺少时返回明确的不可用异常，调用方应
保留原始 PDF 并转人工处理。
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util


class PdfRenderError(RuntimeError):
    """PDF 页面渲染失败。"""


class PdfRenderUnavailable(PdfRenderError):
    """渲染引擎未安装。"""


@dataclass(frozen=True)
class RenderedPdfPage:
    """一页可复核图像及其可追溯参数。"""

    page_number: int
    image_bytes: bytes
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0
    dpi: int = 150
    engine: str = "pymupdf"


def pdf_render_available() -> bool:
    """返回 PyMuPDF 是否可用。"""
    return importlib.util.find_spec("fitz") is not None


def render_pdf_pages(
    body: bytes,
    *,
    page_numbers: list[int] | tuple[int, ...] | None = None,
    dpi: int = 150,
    max_pages: int = 20,
) -> list[RenderedPdfPage]:
    """渲染指定 PDF 页，页码从 1 开始。

    默认最多渲染 20 页，避免扫描版大型报告在桌面进程中一次性消耗过多内存。
    返回的 PNG 字节由上层决定是否归档；本函数不会创建文件或修改数据库。
    """
    if not pdf_render_available():
        raise PdfRenderUnavailable("未安装 PyMuPDF，无法渲染 PDF 页面")
    if not body:
        raise PdfRenderError("PDF 内容为空，无法渲染")
    if dpi < 72 or dpi > 600:
        raise ValueError("dpi 必须在 72–600 之间")
    if max_pages < 1:
        raise ValueError("max_pages 必须大于 0")

    requested = list(page_numbers) if page_numbers is not None else None
    if requested is not None:
        if any(page < 1 for page in requested):
            raise ValueError("page_numbers 必须使用从 1 开始的页码")
        # 保留调用方顺序，同时去重，防止重复渲染同一页。
        requested = list(dict.fromkeys(requested))

    try:
        import fitz  # type: ignore[import-not-found]  # 可选依赖

        document = fitz.open(stream=body, filetype="pdf")
        try:
            total_pages = document.page_count
            numbers = requested if requested is not None else list(range(1, total_pages + 1))
            if len(numbers) > max_pages:
                raise PdfRenderError(
                    f"请求渲染 {len(numbers)} 页，超过安全上限 {max_pages} 页"
                )
            if any(page > total_pages for page in numbers):
                raise PdfRenderError(
                    f"请求页码超出 PDF 范围：共 {total_pages} 页，收到 {numbers}"
                )
            matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            rendered: list[RenderedPdfPage] = []
            for page_number in numbers:
                page = document.load_page(page_number - 1)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                rendered.append(
                    RenderedPdfPage(
                        page_number=page_number,
                        image_bytes=pixmap.tobytes("png"),
                        width=pixmap.width,
                        height=pixmap.height,
                        dpi=dpi,
                    )
                )
            return rendered
        finally:
            document.close()
    except PdfRenderError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转换为可诊断错误
        raise PdfRenderError(f"PDF 页面渲染失败：{exc}") from exc


__all__ = [
    "PdfRenderError",
    "PdfRenderUnavailable",
    "RenderedPdfPage",
    "pdf_render_available",
    "render_pdf_pages",
]
