"""下载结果合法性判断（文档 9.4）。

纯函数：只看 (status_code, content_type, body)，不做任何网络 IO，便于单测。
核心原则——不能只判断 HTTP 200，必须同时看状态码、Content-Type、文件大小、
文件头/魔数，并识别「HTML 拦截页」冒充成功。
"""

from __future__ import annotations

import re

from ..common.enums import AcquisitionErrorCode, ContentKind

# PDF 魔数
_PDF_MAGIC = b"%PDF-"
# ZIP 魔数（xlsx/docx 等 OOXML 均为 zip 容器）
_ZIP_MAGIC = b"PK\x03\x04"
# 老式 xls（复合文档）魔数
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# 常见拦截/验证页特征（大小写不敏感）
_BLOCK_PATTERNS = (
    "access denied",
    "403 forbidden",
    "are you a robot",
    "verifying you are human",
    "captcha",
    "cloudflare",
    "just a moment",
    "请开启 javascript",
    "enable javascript",
    "unusual traffic",
    "请稍候",
    "人机验证",
)


def looks_like_pdf(body: bytes) -> bool:
    """文件头是否为 %PDF-（允许前置极少量空白/BOM）。"""
    head = body[:1024].lstrip(b"\r\n\t \xef\xbb\xbf")
    return head.startswith(_PDF_MAGIC)


def looks_like_html(body: bytes, content_type: str | None = None) -> bool:
    """内容是否为 HTML（据魔数/首部标记，或 content-type 兜底）。"""
    if content_type and "html" in content_type.lower():
        return True
    head = body[:2048].lstrip().lower()
    return (
        head.startswith(b"<!doctype html")
        or head.startswith(b"<html")
        or b"<head" in head
        or b"<body" in head
    )


def is_html_block_page(body: bytes, content_type: str | None = None) -> bool:
    """是否为 HTML 拦截/验证页（返回 200 但实际是反爬/验证页面）。"""
    if not looks_like_html(body, content_type):
        return False
    text = body[:8192].decode("utf-8", errors="ignore").lower()
    return any(p in text for p in _BLOCK_PATTERNS)


def detect_content_kind(body: bytes, content_type: str | None = None) -> ContentKind:
    """据魔数优先、Content-Type 兜底识别内容类型。"""
    if looks_like_pdf(body):
        return ContentKind.PDF
    if body[:8] == _OLE_MAGIC or body[:4] == _ZIP_MAGIC:
        # zip 容器：可能是 xlsx；此处统一归为 EXCEL（csv 是纯文本，不走这里）
        return ContentKind.EXCEL
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return ContentKind.PDF
    if "spreadsheet" in ct or "excel" in ct or ct.endswith("/vnd.ms-excel"):
        return ContentKind.EXCEL
    if "csv" in ct:
        return ContentKind.CSV
    if "json" in ct:
        return ContentKind.JSON
    if looks_like_html(body, content_type):
        return ContentKind.HTML
    # JSON 文本兜底：以 { 或 [ 开头
    head = body[:64].lstrip()
    if head[:1] in (b"{", b"["):
        return ContentKind.JSON
    if "csv" in ct or (b"," in body[:256] and b"\n" in body[:256] and b"<" not in body[:256]):
        return ContentKind.CSV
    return ContentKind.UNKNOWN


def validate_download(
    *,
    status_code: int | None,
    content_type: str | None,
    body: bytes,
    expected: ContentKind = ContentKind.ANY,
    max_bytes: int | None = None,
) -> tuple[AcquisitionErrorCode | None, ContentKind]:
    """校验一次下载是否合法。

    返回 (error_code, detected_kind)。error_code 为 None 表示通过。
    校验顺序：状态码 → 空体 → 大小 → 拦截页 → 期望类型匹配。
    """
    # 1) 状态码
    if status_code is not None and not (200 <= status_code < 300):
        code = {
            403: AcquisitionErrorCode.HTTP_403,
            404: AcquisitionErrorCode.HTTP_404,
            429: AcquisitionErrorCode.HTTP_429,
        }.get(status_code, AcquisitionErrorCode.HTTP_ERROR)
        return code, ContentKind.UNKNOWN

    # 2) 空体
    if not body:
        return AcquisitionErrorCode.EMPTY_BODY, ContentKind.UNKNOWN

    # 3) 大小上限
    if max_bytes is not None and len(body) > max_bytes:
        return AcquisitionErrorCode.TOO_LARGE, ContentKind.UNKNOWN

    detected = detect_content_kind(body, content_type)

    # 4) HTML 拦截页（即便状态码 200 也算失败）
    if is_html_block_page(body, content_type):
        return AcquisitionErrorCode.HTML_BLOCK_PAGE, ContentKind.HTML

    # 5) 期望类型匹配
    if expected == ContentKind.ANY:
        return None, detected
    if expected == ContentKind.PDF:
        if not looks_like_pdf(body):
            return AcquisitionErrorCode.NOT_PDF, detected
        return None, ContentKind.PDF
    if detected != expected:
        return AcquisitionErrorCode.NOT_EXPECTED_TYPE, detected
    return None, detected
