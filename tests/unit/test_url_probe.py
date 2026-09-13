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
        yield b"<html><head><title>Ignored</title></head><body>Three Gorges 2023 generation</body></html>"


class _Utf8HtmlResponse(_Response):
    headers = {"Content-Type": "text/html"}
    encoding = "ISO-8859-1"

    def iter_content(self, chunk_size):
        yield "<html><body>三峡电站 2023 年全年发电量</body></html>".encode("utf-8")


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


def test_probe_adds_bounded_html_preview_without_archiving_content():
    result = UrlProbe(session=_Session(_HtmlResponse(200, "https://example.test/report"))).probe(
        {"url": "https://example.test/report", "metadata": {"search_title": "Report"}}
    )

    assert "Three Gorges 2023 generation" in result["metadata"]["content_preview"]
    assert result["metadata"]["search_title"] == "Report"


def test_probe_detects_utf8_html_when_server_uses_default_latin1_encoding():
    result = UrlProbe(session=_Session(_Utf8HtmlResponse(200, "https://example.test/chinese"))).probe(
        {"url": "https://example.test/chinese"}
    )

    assert "三峡电站 2023 年全年发电量" in result["metadata"]["content_preview"]
