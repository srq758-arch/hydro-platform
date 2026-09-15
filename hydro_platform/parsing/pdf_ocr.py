"""PDF OCR 适配层（D4）。

本模块只负责把渲染后的页面交给 OCR 引擎并返回带审计元数据的文本。它不做
业务字段推断，也不把 OCR 文本直接写入正式事实；调用方必须把结果作为待复核
证据处理。Pytesseract/Pillow 均为可选依赖，支持注入 fake backend 做离线测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib.util
from io import BytesIO
import re
import shutil
from typing import Protocol, Sequence

from .pdf_renderer import RenderedPdfPage


class PdfOcrError(RuntimeError):
    """OCR 执行失败。"""


class PdfOcrUnavailable(PdfOcrError):
    """OCR 依赖或本机 OCR 引擎不可用。"""


@dataclass(frozen=True)
class OcrRegion:
    """页面像素坐标区域，使用左上角原点。"""

    x0: int
    y0: int
    x1: int
    y1: int

    def validate(self, *, width: int, height: int) -> None:
        if not (0 <= self.x0 < self.x1 <= width and 0 <= self.y0 < self.y1 <= height):
            raise ValueError(
                f"OCR 区域越界：({self.x0},{self.y0},{self.x1},{self.y1})，"
                f"页面尺寸为 {width}x{height}"
            )


@dataclass(frozen=True)
class OcrPageText:
    """一页 OCR 文本及其证据元数据。"""

    page_number: int
    text: str
    engine: str
    engine_version: str | None
    language: str
    region: OcrRegion | None
    source_image_sha256: str


class OcrBackend(Protocol):
    """可注入的 OCR 后端协议。"""

    name: str
    version: str | None

    def recognize(self, image_bytes: bytes, *, language: str, config: str = "") -> str:
        ...


class PytesseractBackend:
    """基于 pytesseract 的可选后端。"""

    name = "pytesseract"

    def __init__(self) -> None:
        if importlib.util.find_spec("pytesseract") is None:
            raise PdfOcrUnavailable("未安装 pytesseract，请安装可选 OCR 依赖")
        try:
            import pytesseract  # type: ignore[import-not-found]

            self._pytesseract = pytesseract
            self.version = str(pytesseract.get_tesseract_version())
            try:
                self.languages = tuple(str(item) for item in pytesseract.get_languages(config=""))
            except Exception:  # noqa: BLE001 - 引擎可用但语言包探测失败时交给引擎处理
                self.languages = ()
        except Exception as exc:  # noqa: BLE001 - 依赖/本机二进制统一报错
            raise PdfOcrUnavailable(f"Tesseract 引擎不可用：{exc}") from exc

    def recognize(self, image_bytes: bytes, *, language: str, config: str = "") -> str:
        try:
            from PIL import Image  # type: ignore[import-not-found]

            with Image.open(BytesIO(image_bytes)) as image:
                return str(
                    self._pytesseract.image_to_string(
                        image, lang=language, config=config
                    )
                ).strip()
        except Exception as exc:  # noqa: BLE001 - 保留页码由上层处理
            raise PdfOcrError(f"Tesseract OCR 失败：{exc}") from exc


def ocr_available() -> bool:
    """探测 pytesseract 与本机 Tesseract 是否都可用。"""
    if importlib.util.find_spec("pytesseract") is None:
        return False
    try:
        PytesseractBackend()
        return True
    except PdfOcrUnavailable:
        return False


def ocr_environment_report() -> dict:
    """返回当前机器的真实 OCR 能力，不执行采集、不写文件。"""
    package_pytesseract = importlib.util.find_spec("pytesseract") is not None
    package_pillow = importlib.util.find_spec("PIL") is not None
    binary_path = shutil.which("tesseract")
    version = None
    languages: list[str] = []
    errors: list[str] = []
    if package_pytesseract:
        try:
            import pytesseract  # type: ignore[import-not-found]

            version = str(pytesseract.get_tesseract_version())
            try:
                languages = list(pytesseract.get_languages(config=""))
            except Exception as exc:  # noqa: BLE001 - 语言包探测失败仍返回主状态
                errors.append(f"语言包探测失败：{exc}")
        except Exception as exc:  # noqa: BLE001 - 二进制缺失/不可执行
            errors.append(f"Tesseract 引擎不可用：{exc}")
    else:
        errors.append("未安装 pytesseract")
    if not binary_path:
        errors.append("未找到 tesseract 二进制")
    if not package_pillow:
        errors.append("未安装 Pillow")
    available = package_pytesseract and package_pillow and bool(binary_path) and version is not None
    return {
        "available": available,
        "dependencies": {
            "pymupdf": importlib.util.find_spec("fitz") is not None,
            "pillow": package_pillow,
            "pytesseract": package_pytesseract,
        },
        "tesseract": {
            "binary_path": binary_path,
            "version": version,
            "languages": languages,
        },
        "errors": errors,
        "recommendation": (
            "可执行扫描 PDF OCR"
            if available
            else "安装项目 OCR 可选依赖，并在系统 PATH 中配置 Tesseract 及所需语言包"
        ),
    }


def _validate_requested_languages(backend: OcrBackend, language: str) -> None:
    """若后端能列出语言包，则在首个页面前给出明确的缺包错误。"""
    available = getattr(backend, "languages", None)
    if not available:
        return
    requested = tuple(
        token.strip() for token in re.split(r"[+,]", language) if token.strip()
    )
    missing = [token for token in requested if token not in available]
    if missing:
        available_text = ", ".join(str(item) for item in available)
        raise PdfOcrUnavailable(
            f"OCR 语言包缺失：{', '.join(missing)}；当前可用语言：{available_text or '无'}"
        )


def ocr_rendered_pages(
    pages: Sequence[RenderedPdfPage],
    *,
    backend: OcrBackend | None = None,
    language: str = "eng",
    config: str = "",
    regions: dict[int, OcrRegion] | None = None,
) -> list[OcrPageText]:
    """对已渲染页面执行 OCR，并保留原图/区域追踪信息。

    ``regions`` 使用 1-based 页码；传入区域时仅对该区域裁剪后 OCR，避免对整份
    报告无差别识别。未传区域则识别整页，但仍返回原图哈希供复核。
    """
    if backend is None:
        backend = PytesseractBackend()
    if not language.strip():
        raise ValueError("language 不能为空")
    _validate_requested_languages(backend, language)

    output: list[OcrPageText] = []
    for page in pages:
        region = regions.get(page.page_number) if regions else None
        image_bytes = page.image_bytes
        if region is not None:
            region.validate(width=page.width, height=page.height)
            try:
                from PIL import Image  # type: ignore[import-not-found]

                with Image.open(BytesIO(page.image_bytes)) as image:
                    cropped = image.crop((region.x0, region.y0, region.x1, region.y1))
                    buffer = BytesIO()
                    cropped.save(buffer, format="PNG")
                    image_bytes = buffer.getvalue()
            except Exception as exc:  # noqa: BLE001 - 区域裁剪失败需可诊断
                raise PdfOcrError(f"OCR 区域裁剪失败（第 {page.page_number} 页）：{exc}") from exc
        text = backend.recognize(image_bytes, language=language, config=config)
        output.append(
            OcrPageText(
                page_number=page.page_number,
                text=text,
                engine=getattr(backend, "name", backend.__class__.__name__),
                engine_version=getattr(backend, "version", None),
                language=language,
                region=region,
                source_image_sha256=sha256(page.image_bytes).hexdigest(),
            )
        )
    return output


__all__ = [
    "OcrBackend",
    "OcrPageText",
    "OcrRegion",
    "PdfOcrError",
    "PdfOcrUnavailable",
    "PytesseractBackend",
    "ocr_available",
    "ocr_environment_report",
    "ocr_rendered_pages",
]
