"""URL 访问预检必须将失效链接隔离出可采集候选。"""

import requests

from hydro_platform.discovery.url_probe import UrlProbe


class _Response:
    def __init__(self, status_code, url):
        self.status_code = status_code
        self.url = url
        self.closed = False

    def close(self):
        self.closed = True


class _HtmlResponse(_Response):
    headers = {"Content-Type": "text/html; charset=utf-8"}
    encoding = "utf-8"

    def iter_content(self, chunk_size):
        yield b'<html><head><title>Ignored</title></head><body>Three Gorges 2023 generation<a href="/files/report-2023.pdf">Annual report PDF</a></body></html>'


class _Utf8HtmlResponse(_Response):
    headers = {"Content-Type": "text/html"}
    encoding = "ISO-8859-1"

    def iter_content(self, chunk_size):
        yield "<html><body>三峡电站 2023 年全年发电量</body></html>".encode("utf-8")


class _BrokenPdfResponse(_Response):
    headers = {"Content-Type": "application/pdf"}
    encoding = None

    def iter_content(self, chunk_size):
        yield b"%PDF-1.4\ninvalid truncated object table"


class _OctetStreamPdfResponse(_BrokenPdfResponse):
    headers = {"Content-Type": "application/octet-stream"}


class _HtmlChallengeResponse(_Response):
    headers = {"Content-Type": "text/html; charset=utf-8"}
    encoding = "utf-8"

    def iter_content(self, chunk_size):
        yield b"<html><body>browser verification required</body></html>"


class _Session:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def get(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response


def test_probe_marks_successful_url_reachable_and_closes_response():
    response = _Response(200, "https://example.test/final")
    result = UrlProbe(session=_Session(response)).probe({"url": "https://example.test/start"})

    assert result["access_status"] == "reachable"
    assert result["http_status"] == 200
    assert result["final_url"] == "https://example.test/final"
    assert response.closed is True


def test_probe_marks_404_unavailable():
    result = UrlProbe(session=_Session(_Response(404, "https://example.test/missing"))).probe(
        {"url": "https://example.test/missing"}
    )

    assert result["access_status"] == "unavailable"
    assert result["status"] == "unavailable"
    assert result["error"] == "HTTP 404"


def test_probe_preserves_403_for_browser_fallback():
    result = UrlProbe(session=_Session(_Response(403, "https://example.test/protected"))).probe(
        {"url": "https://example.test/protected"}
    )

    assert result["access_status"] == "requires_browser"
    assert result["status"] == "discovered"


def test_probe_marks_network_failure_unknown():
    result = UrlProbe(session=_Session(error=requests.ConnectionError("offline"))).probe(
        {"url": "https://example.test/offline"}
    )

    assert result["access_status"] == "unknown"
    assert result["status"] == "unavailable"


def test_malformed_pdf_preview_does_not_abort_probe_batch():
    probe = UrlProbe(session=_Session(_BrokenPdfResponse(200, "https://example.test/broken.pdf")))
    result = probe.probe({"url": "https://example.test/broken.pdf", "metadata": {"verify_pdf_text": True}})

    assert result["access_status"] == "reachable"
    assert result["http_status"] == 200
    assert result["metadata"].get("content_preview", "") == ""
    assert result["status"] == "discovered"


def test_probe_adds_bounded_html_preview_without_archiving_content():
    result = UrlProbe(session=_Session(_HtmlResponse(200, "https://example.test/report"))).probe(
        {"url": "https://example.test/report", "metadata": {"search_title": "Report"}}
    )

    assert "Three Gorges 2023 generation" in result["metadata"]["content_preview"]
    assert result["metadata"]["search_title"] == "Report"
    assert result["metadata"]["discovered_links"] == [{
        "url": "https://example.test/files/report-2023.pdf", "text": "Annual report PDF",
    }]


def test_probe_detects_utf8_html_when_server_uses_default_latin1_encoding():
    result = UrlProbe(session=_Session(_Utf8HtmlResponse(200, "https://example.test/chinese"))).probe(
        {"url": "https://example.test/chinese"}
    )

    assert "三峡电站 2023 年全年发电量" in result["metadata"]["content_preview"]


def test_pdf_document_type_enables_bounded_preview_without_extra_flag(monkeypatch):
    called = []
    monkeypatch.setattr(
        UrlProbe, "_official_pdf_preview",
        staticmethod(lambda response: called.append(response.url) or "Itaipu 2023 annual generation"),
    )
    response = _BrokenPdfResponse(200, "https://example.test/report.pdf")
    result = UrlProbe(session=_Session(response)).probe(
        {"url": "https://example.test/report.pdf", "document_type": "pdf"}
    )

    assert called == ["https://example.test/report.pdf"]
    assert result["metadata"]["content_preview"] == "Itaipu 2023 annual generation"


def test_pdf_url_is_previewed_when_server_uses_octet_stream(monkeypatch):
    called = []
    monkeypatch.setattr(
        UrlProbe, "_official_pdf_preview",
        staticmethod(lambda response: called.append(response.url) or "三峡电站 2024 年度发电量"),
    )
    response = _OctetStreamPdfResponse(200, "https://example.test/report.pdf")
    result = UrlProbe(session=_Session(response)).probe(
        {"url": "https://example.test/report.pdf"}
    )

    assert called == ["https://example.test/report.pdf"]
    assert result["metadata"]["content_preview"] == "三峡电站 2024 年度发电量"


def test_pdf_url_returning_html_is_sent_to_browser_fallback():
    response = _HtmlChallengeResponse(200, "https://example.test/report.pdf")
    result = UrlProbe(session=_Session(response)).probe(
        {"url": "https://example.test/report.pdf", "document_type": "pdf"}
    )

    assert result["access_status"] == "requires_browser"
    assert result["status"] == "discovered"
    assert "需要浏览器验证" in result["error"]
