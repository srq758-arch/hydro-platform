"""下载合法性判断单测（文档 9.4）——纯函数，无网络。"""

from __future__ import annotations

from hydro_platform.common.enums import AcquisitionErrorCode, ContentKind
from hydro_platform.acquisition.validators import (
    detect_content_kind,
    is_html_block_page,
    looks_like_html,
    looks_like_pdf,
    validate_download,
)

PDF_BODY = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n" + b"x" * 500
XLSX_BODY = b"PK\x03\x04" + b"\x00" * 500
JSON_BODY = b'{"year": 2024, "gwh": 123.4}'
HTML_BODY = b"<!DOCTYPE html><html><head><title>Report</title></head><body>ok</body></html>"
BLOCK_BODY = (
    b"<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
    b"<body>Verifying you are human. Please enable JavaScript.</body></html>"
)


def test_looks_like_pdf():
    assert looks_like_pdf(PDF_BODY) is True
    assert looks_like_pdf(b"\xef\xbb\xbf%PDF-1.4") is True  # 允许 BOM 前缀
    assert looks_like_pdf(HTML_BODY) is False


def test_looks_like_html():
    assert looks_like_html(HTML_BODY) is True
    assert looks_like_html(b"garbage", content_type="text/html; charset=utf-8") is True
    assert looks_like_html(PDF_BODY) is False


def test_is_html_block_page():
    assert is_html_block_page(BLOCK_BODY) is True
    assert is_html_block_page(HTML_BODY) is False   # 正常 HTML 不算拦截页
    assert is_html_block_page(PDF_BODY) is False     # 非 HTML 直接 False


def test_detect_content_kind():
    assert detect_content_kind(PDF_BODY) == ContentKind.PDF
    assert detect_content_kind(XLSX_BODY) == ContentKind.EXCEL
    assert detect_content_kind(JSON_BODY, "application/json") == ContentKind.JSON
    assert detect_content_kind(JSON_BODY) == ContentKind.JSON  # 无 CT 也能按 { 兜底
    assert detect_content_kind(HTML_BODY) == ContentKind.HTML


def test_validate_download_pass_pdf():
    err, kind = validate_download(
        status_code=200, content_type="application/pdf", body=PDF_BODY,
        expected=ContentKind.PDF,
    )
    assert err is None
    assert kind == ContentKind.PDF


def test_validate_download_not_pdf_when_html():
    # 服务器返回 200 + HTML，但期望 PDF → NOT_PDF
    err, kind = validate_download(
        status_code=200, content_type="text/html", body=HTML_BODY,
        expected=ContentKind.PDF,
    )
    assert err == AcquisitionErrorCode.NOT_PDF


def test_validate_download_block_page_beats_200():
    err, kind = validate_download(
        status_code=200, content_type="text/html", body=BLOCK_BODY,
        expected=ContentKind.ANY,
    )
    assert err == AcquisitionErrorCode.HTML_BLOCK_PAGE


def test_validate_download_status_codes():
    for code, expected in [
        (403, AcquisitionErrorCode.HTTP_403),
        (404, AcquisitionErrorCode.HTTP_404),
        (429, AcquisitionErrorCode.HTTP_429),
        (500, AcquisitionErrorCode.HTTP_ERROR),
    ]:
        err, _ = validate_download(
            status_code=code, content_type="text/html", body=HTML_BODY,
        )
        assert err == expected


def test_validate_download_empty_and_too_large():
    err, _ = validate_download(status_code=200, content_type="application/pdf", body=b"")
    assert err == AcquisitionErrorCode.EMPTY_BODY

    err, _ = validate_download(
        status_code=200, content_type="application/pdf", body=PDF_BODY, max_bytes=10,
    )
    assert err == AcquisitionErrorCode.TOO_LARGE


def test_validate_download_expected_type_mismatch():
    err, kind = validate_download(
        status_code=200, content_type="application/json", body=JSON_BODY,
        expected=ContentKind.EXCEL,
    )
    assert err == AcquisitionErrorCode.NOT_EXPECTED_TYPE
    assert kind == ContentKind.JSON
