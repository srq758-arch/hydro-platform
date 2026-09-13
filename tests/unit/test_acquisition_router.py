"""Acquisition 路由单测：HTTP 成功直返；可回退错误在有浏览器时改走浏览器。"""

from __future__ import annotations

from hydro_platform.common.enums import AccessMethod, AcquisitionErrorCode, ContentKind
from hydro_platform.acquisition.http_client import HttpClient, HttpClientConfig
from hydro_platform.acquisition.result import DownloadMeta, FetchResult
from hydro_platform.acquisition.router import AcquisitionRouter
from hydro_platform.acquisition.transport import RawResponse, TransportError

PDF_BODY = b"%PDF-1.7\n" + b"data" * 100
BLOCK_BODY = (
    b"<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
    b"<body>captcha verifying you are human</body></html>"
)


class ScriptedTransport:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def fetch(self, url, *, headers, timeout):
        self.calls += 1
        item = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


class FakeBrowser:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def fetch(self, url, *, expected=ContentKind.ANY):
        self.calls += 1
        return self.result


def _http(transport):
    return HttpClient(transport=transport, config=HttpClientConfig(max_attempts=1),
                      sleep=lambda s: None)


def _resp(status=200, ct="application/pdf", body=PDF_BODY):
    return RawResponse(status, {"Content-Type": ct}, body, "https://e.org/f.pdf")


def _browser_ok():
    meta = DownloadMeta(
        original_url="u", final_url="u", status_code=200, content_type="application/pdf",
        file_size=len(PDF_BODY), content_hash="h", content_kind=ContentKind.PDF,
        access_method=AccessMethod.BROWSER, fetched_at="2026-01-01T00:00:00+00:00",
    )
    return FetchResult.ok(meta=meta, body=PDF_BODY)


def test_http_success_returns_without_browser():
    t = ScriptedTransport([_resp()])
    browser = FakeBrowser(_browser_ok())
    router = AcquisitionRouter(http_client=_http(t), browser_client=browser)
    res = router.fetch("https://e.org/x.pdf", expected=ContentKind.PDF)
    assert res.success
    assert res.meta.access_method == AccessMethod.HTTP
    assert browser.calls == 0


def test_block_page_falls_back_to_browser():
    t = ScriptedTransport([_resp(status=200, ct="text/html", body=BLOCK_BODY)])
    browser = FakeBrowser(_browser_ok())
    router = AcquisitionRouter(http_client=_http(t), browser_client=browser)
    res = router.fetch("https://e.org/x.pdf", expected=ContentKind.PDF)
    assert res.success
    assert res.meta.access_method == AccessMethod.BROWSER
    assert browser.calls == 1


def test_404_does_not_fall_back():
    # 404 不属可回退错误，不该动用浏览器
    t = ScriptedTransport([_resp(status=404, ct="text/html", body=b"<html>nope</html>")])
    browser = FakeBrowser(_browser_ok())
    router = AcquisitionRouter(http_client=_http(t), browser_client=browser)
    res = router.fetch("https://e.org/x.pdf", expected=ContentKind.PDF)
    assert not res.success
    assert res.error_code == AcquisitionErrorCode.HTTP_404
    assert browser.calls == 0


def test_no_browser_returns_http_failure_honestly():
    # 无浏览器客户端时，可回退错误也如实返回 HTTP 失败，不静默成功
    t = ScriptedTransport([_resp(status=403, ct="text/html", body=b"<html>denied</html>")])
    router = AcquisitionRouter(http_client=_http(t), browser_client=None)
    res = router.fetch("https://e.org/x.pdf", expected=ContentKind.PDF)
    assert not res.success
    assert res.error_code == AcquisitionErrorCode.HTTP_403


def test_fallback_disabled_flag():
    t = ScriptedTransport([_resp(status=403, ct="text/html", body=b"<html>denied</html>")])
    browser = FakeBrowser(_browser_ok())
    router = AcquisitionRouter(http_client=_http(t), browser_client=browser)
    res = router.fetch("https://e.org/x.pdf", expected=ContentKind.PDF,
                       allow_browser_fallback=False)
    assert not res.success
    assert browser.calls == 0


def test_fallback_wires_real_browser_client_with_fake_driver():
    # 用真实 PlaywrightBrowserClient + 假驱动，验证回退全链路端到端
    from hydro_platform.acquisition.browser_client import PlaywrightBrowserClient
    from hydro_platform.acquisition.transport import RawResponse as RR

    class FakeDriver:
        def navigate(self, url, *, config):
            return RR(200, {"Content-Type": "application/pdf"}, PDF_BODY, "https://e.org/f.pdf")

    t = ScriptedTransport([_resp(status=403, ct="text/html", body=b"<html>denied</html>")])
    browser = PlaywrightBrowserClient(FakeDriver())
    router = AcquisitionRouter(http_client=_http(t), browser_client=browser)
    res = router.fetch("https://e.org/x.pdf", expected=ContentKind.PDF)
    assert res.success
    assert res.meta.access_method == AccessMethod.BROWSER
