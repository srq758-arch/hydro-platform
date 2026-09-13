"""Playwright 浏览器客户端单测：用假 BrowserDriver，完全离线，不碰真实浏览器。"""

from __future__ import annotations

from hydro_platform.common.enums import AccessMethod, AcquisitionErrorCode, ContentKind
from hydro_platform.acquisition.browser_client import (
    BrowserConfig,
    BrowserError,
    PlaywrightBrowserClient,
    create_browser_client,
    playwright_available,
)
from hydro_platform.acquisition.transport import RawResponse

PDF_BODY = b"%PDF-1.7\n" + b"data" * 100
BLOCK_BODY = (
    b"<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
    b"<body>captcha verifying you are human</body></html>"
)
RENDERED_HTML = b"<!DOCTYPE html><html><body><h1>Annual Report 2024</h1></body></html>"


class FakeDriver:
    """返回预设 RawResponse 或抛 BrowserError。"""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0
        self.last_config = None

    def navigate(self, url, *, config):
        self.calls += 1
        self.last_config = config
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _client(outcome, config=None):
    return PlaywrightBrowserClient(FakeDriver(outcome), config)


def test_browser_success_pdf_download():
    resp = RawResponse(200, {"Content-Type": "application/pdf"}, PDF_BODY, "https://e.org/f.pdf")
    client = _client(resp)
    res = client.fetch("https://e.org/x", expected=ContentKind.PDF)
    assert res.success
    assert res.meta.access_method == AccessMethod.BROWSER
    assert res.meta.content_kind == ContentKind.PDF
    assert res.body == PDF_BODY


def test_browser_rendered_html_success():
    resp = RawResponse(200, {"Content-Type": "text/html"}, RENDERED_HTML, "https://e.org/final")
    client = _client(resp)
    res = client.fetch("https://e.org/x", expected=ContentKind.HTML)
    assert res.success
    assert res.meta.content_kind == ContentKind.HTML
    assert res.meta.final_url == "https://e.org/final"


def test_browser_block_page_still_fails_through_shared_validator():
    # 浏览器拿到的仍是拦截页 → 复用同一校验，判 HTML_BLOCK_PAGE
    resp = RawResponse(200, {"Content-Type": "text/html"}, BLOCK_BODY, "https://e.org/x")
    client = _client(resp)
    res = client.fetch("https://e.org/x", expected=ContentKind.ANY)
    assert not res.success
    assert res.error_code == AcquisitionErrorCode.HTML_BLOCK_PAGE
    assert res.meta is not None  # 失败也带 meta


def test_browser_launch_failure():
    client = _client(BrowserError(AcquisitionErrorCode.BROWSER_LAUNCH_FAILED, "no edge"))
    res = client.fetch("https://e.org/x")
    assert not res.success
    assert res.error_code == AcquisitionErrorCode.BROWSER_LAUNCH_FAILED


def test_browser_navigation_failure():
    client = _client(BrowserError(AcquisitionErrorCode.BROWSER_NAVIGATION_FAILED, "timeout"))
    res = client.fetch("https://e.org/x")
    assert not res.success
    assert res.error_code == AcquisitionErrorCode.BROWSER_NAVIGATION_FAILED


def test_browser_download_failure():
    client = _client(BrowserError(AcquisitionErrorCode.BROWSER_DOWNLOAD_FAILED, "click failed"))
    res = client.fetch("https://e.org/x", expected=ContentKind.PDF)
    assert not res.success
    assert res.error_code == AcquisitionErrorCode.BROWSER_DOWNLOAD_FAILED


def test_config_passed_to_driver():
    resp = RawResponse(200, {"Content-Type": "application/pdf"}, PDF_BODY, "https://e.org/f.pdf")
    driver = FakeDriver(resp)
    cfg = BrowserConfig(headless=False, nav_timeout=10.0)
    client = PlaywrightBrowserClient(driver, cfg)
    client.fetch("https://e.org/x")
    assert driver.last_config is cfg
    assert driver.last_config.headless is False


def test_create_browser_client_none_when_unavailable(monkeypatch):
    # 环境是否安装 playwright 不应影响单测；显式模拟可选依赖缺失。
    import hydro_platform.acquisition.browser_client as browser_module

    monkeypatch.setattr(browser_module, "playwright_available", lambda: False)
    assert create_browser_client() is None
