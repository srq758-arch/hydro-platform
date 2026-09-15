"""D4 OCR 适配层测试：注入后端，避免测试依赖本机 Tesseract。"""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO

import pytest

from hydro_platform.parsing.pdf_ocr import (
    OcrRegion,
    PdfOcrError,
    PdfOcrUnavailable,
    ocr_environment_report,
    ocr_rendered_pages,
)
from hydro_platform.parsing.pdf_renderer import RenderedPdfPage


def _png_bytes(width: int = 100, height: int = 80) -> bytes:
    pil = __import__("importlib").util.find_spec("PIL")
    if pil is None:
        pytest.skip("Pillow 未安装")
    from PIL import Image

    image = Image.new("RGB", (width, height), "white")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class FakeOcrBackend:
    name = "fake-ocr"
    version = "test-1"

    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, str]] = []

    def recognize(self, image_bytes: bytes, *, language: str, config: str = "") -> str:
        self.calls.append((image_bytes, language, config))
        return "Three Gorges Dam 829.11 GWh"


def test_ocr_rendered_pages_keeps_page_region_engine_and_source_hash():
    image = _png_bytes()
    backend = FakeOcrBackend()
    result = ocr_rendered_pages(
        [RenderedPdfPage(page_number=2, image_bytes=image, width=100, height=80, dpi=150)],
        backend=backend,
        language="eng",
        config="--psm 6",
        regions={2: OcrRegion(10, 10, 90, 70)},
    )
    assert len(result) == 1
    page = result[0]
    assert page.page_number == 2
    assert page.text == "Three Gorges Dam 829.11 GWh"
    assert page.engine == "fake-ocr"
    assert page.engine_version == "test-1"
    assert page.language == "eng"
    assert page.region == OcrRegion(10, 10, 90, 70)
    assert page.source_image_sha256 == sha256(image).hexdigest()
    assert backend.calls[0][1:] == ("eng", "--psm 6")
    # 区域 OCR 使用裁剪图，不会把原图字节直接交给后端。
    assert backend.calls[0][0] != image


def test_ocr_rendered_pages_rejects_out_of_bounds_region():
    with pytest.raises(ValueError, match="OCR 区域越界"):
        ocr_rendered_pages(
            [RenderedPdfPage(page_number=1, image_bytes=_png_bytes(), width=100, height=80)],
            backend=FakeOcrBackend(),
            regions={1: OcrRegion(0, 0, 101, 80)},
        )


def test_ocr_rendered_pages_propagates_backend_error():
    class FailingBackend(FakeOcrBackend):
        def recognize(self, image_bytes: bytes, *, language: str, config: str = "") -> str:
            raise PdfOcrError("fake OCR failure")

    with pytest.raises(PdfOcrError, match="fake OCR failure"):
        ocr_rendered_pages(
            [RenderedPdfPage(page_number=1, image_bytes=_png_bytes(), width=100, height=80)],
            backend=FailingBackend(),
        )


def test_ocr_rendered_pages_reports_missing_language_pack_before_rendering():
    class LanguageAwareBackend(FakeOcrBackend):
        languages = ("eng",)

    with pytest.raises(PdfOcrUnavailable, match="语言包缺失.*chi_sim"):
        ocr_rendered_pages(
            [RenderedPdfPage(page_number=1, image_bytes=_png_bytes(), width=100, height=80)],
            backend=LanguageAwareBackend(),
            language="eng+chi_sim",
        )


def test_ocr_environment_report_is_actionable():
    report = ocr_environment_report()
    assert isinstance(report["available"], bool)
    assert set(report["dependencies"]) == {"pymupdf", "pillow", "pytesseract"}
    assert "tesseract" in report
    assert isinstance(report["errors"], list)
    assert report["recommendation"]
