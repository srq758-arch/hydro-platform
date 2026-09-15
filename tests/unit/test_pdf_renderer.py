"""D4 PDF 页面渲染基础设施的真实行为测试。"""

from __future__ import annotations

from io import BytesIO

import pytest

from hydro_platform.parsing.pdf_renderer import (
    PdfRenderError,
    pdf_render_available,
    render_pdf_pages,
)


def _two_page_pdf() -> bytes:
    reportlab = __import__("importlib").util.find_spec("reportlab")
    if reportlab is None:
        pytest.skip("reportlab 未安装")
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    stream = BytesIO()
    page = canvas.Canvas(stream, pagesize=letter)
    page.drawString(40, 740, "Page 1: Annual Generation")
    page.showPage()
    page.drawString(40, 740, "Page 2: Annual Generation")
    page.save()
    return stream.getvalue()


def test_render_pdf_pages_returns_png_with_traceable_parameters():
    if not pdf_render_available():
        pytest.skip("PyMuPDF 未安装")
    pages = render_pdf_pages(_two_page_pdf(), page_numbers=[2, 1], dpi=100)
    assert [page.page_number for page in pages] == [2, 1]
    assert all(page.mime_type == "image/png" for page in pages)
    assert all(page.image_bytes.startswith(b"\x89PNG\r\n\x1a\n") for page in pages)
    assert all(page.engine == "pymupdf" and page.dpi == 100 for page in pages)
    assert all(page.width > 0 and page.height > 0 for page in pages)


def test_render_pdf_pages_deduplicates_and_enforces_page_limit():
    if not pdf_render_available():
        pytest.skip("PyMuPDF 未安装")
    body = _two_page_pdf()
    pages = render_pdf_pages(body, page_numbers=[1, 1], max_pages=1)
    assert [page.page_number for page in pages] == [1]
    with pytest.raises(PdfRenderError, match="安全上限"):
        render_pdf_pages(body, page_numbers=[1, 2], max_pages=1)


def test_render_pdf_pages_rejects_invalid_request():
    if not pdf_render_available():
        pytest.skip("PyMuPDF 未安装")
    body = _two_page_pdf()
    with pytest.raises(ValueError, match="dpi"):
        render_pdf_pages(body, dpi=40)
    with pytest.raises(PdfRenderError, match="超出 PDF 范围"):
        render_pdf_pages(body, page_numbers=[3])
