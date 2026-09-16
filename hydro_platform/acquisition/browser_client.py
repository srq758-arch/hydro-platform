"""Playwright 浏览器访问（文档 9.3）——可选依赖。

当 HTTP/API 因需要 JavaScript、被反爬拦截或被拒绝而失败时，路由回退到这里。
浏览器客户端自动：启动 Edge/Chrome（优先 Edge，独立自动化 Profile）→ 打开 URL
→ 等待加载 → 执行 JS/处理重定向与 Cookie → 必要时点击下载 → 保存内容。

设计要点：
- playwright 是重依赖（需下载浏览器二进制），故延迟导入。未安装时 create_browser_client()
  返回 None，路由如实返回 HTTP 失败，不静默成功。
- 实际驱动浏览器的动作抽象成 BrowserDriver（对标 Transport），生产用 PlaywrightDriver，
  测试注入假驱动即可完全离线，不碰真实浏览器。
- 下载后复用 finalize.finalize_response 做同一套合法性校验，口径与 HTTP 一致。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from ..common.enums import AccessMethod, AcquisitionErrorCode, ContentKind
from ..common.logging_setup import get_logger
from .finalize import finalize_response
from .result import FetchResult
from .transport import RawResponse

logger = get_logger(__name__)

# 浏览器优先级（文档 9.3）：Edge 优先，其次 Chrome。
BROWSER_PRIORITY = ("msedge", "chrome")


@dataclass
class BrowserConfig:
    """浏览器访问策略参数。"""

    channels: tuple[str, ...] = BROWSER_PRIORITY
    # 对已被 HTTP 拦截的站点，headless Chromium 常会再次被识别为机器人。
    # 默认用可见但独立的临时会话：不读取用户浏览器 Cookie，也不复用个人资料。
    headless: bool = False
    nav_timeout: float = 30.0            # 单页导航超时（秒）
    wait_until: str = "domcontentloaded" # 不等待广告/统计请求，减少被长连接拖超时
    user_data_dir: str | None = None     # 独立自动化 Profile 目录（None=临时）
    max_bytes: int = 100 * 1024 * 1024
    download_click_selector: str | None = None  # 需点击才触发下载时的选择器


class BrowserError(Exception):
    """浏览器驱动错误，携带归一化错误码（文档 9.4 BROWSER_*）。"""

    def __init__(self, code: AcquisitionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class BrowserDriver(Protocol):
    """浏览器驱动接口：打开 URL 并返回原始响应，或抛 BrowserError。"""

    def navigate(
        self,
        url: str,
        *,
        config: BrowserConfig,
    ) -> RawResponse:  # pragma: no cover - 协议声明
        ...


class PlaywrightBrowserClient:
    """在 BrowserDriver 之上产出统一 FetchResult 的浏览器客户端。"""

    def __init__(
        self,
        driver: BrowserDriver,
        config: BrowserConfig | None = None,
    ) -> None:
        self.driver = driver
        self.config = config or BrowserConfig()

    def fetch(
        self,
        url: str,
        *,
        expected: ContentKind = ContentKind.ANY,
    ) -> FetchResult:
        """用浏览器获取 url 并校验。驱动异常归一为 BROWSER_* 失败码。"""
        started = time.perf_counter()
        try:
            resp = self.driver.navigate(url, config=self.config)
        except BrowserError as exc:
            logger.warning("浏览器获取失败[%s] %s", exc.code.value, url)
            return FetchResult.fail(exc.code, str(exc))

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        result = finalize_response(
            url, resp,
            expected=expected,
            access_method=AccessMethod.BROWSER,
            max_bytes=self.config.max_bytes,
            elapsed_ms=elapsed_ms,
        )
        if result.success:
            logger.info(
                "浏览器获取成功 %s → %s（%s, %d bytes）",
                url, resp.final_url, result.meta.content_kind.value, result.meta.file_size,
            )
        return result


def playwright_available() -> bool:
    """playwright 是否已安装（不启动浏览器，仅探测导入）。"""
    import importlib.util

    return importlib.util.find_spec("playwright") is not None


def create_browser_client(
    config: BrowserConfig | None = None,
) -> PlaywrightBrowserClient | None:
    """构造真实浏览器客户端；playwright 未安装则返回 None（路由据此优雅降级）。"""
    if not playwright_available():
        logger.info("playwright 未安装，浏览器回退不可用")
        return None
    driver = PlaywrightDriver()
    return PlaywrightBrowserClient(driver, config)


class PlaywrightDriver:
    """基于 playwright 同步 API 的真实驱动（延迟导入，未装则构造即报错）。

    仅在 create_browser_client() 确认可用后实例化。逐个尝试 Edge→Chrome 渠道，
    用独立 persistent context 承载自动化 Profile。
    """

    def __init__(self) -> None:  # pragma: no cover - 需真实 playwright 环境
        from playwright.sync_api import sync_playwright  # 延迟导入

        self._sync_playwright = sync_playwright

    def navigate(self, url: str, *, config: BrowserConfig) -> RawResponse:  # pragma: no cover
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import TimeoutError as PWTimeout

        with self._sync_playwright() as pw:
            browser = None
            last_err: Exception | None = None
            for channel in config.channels:
                try:
                    browser = pw.chromium.launch(channel=channel, headless=config.headless)
                    break
                except PWError as exc:
                    last_err = exc
                    continue
            if browser is None:
                raise BrowserError(
                    AcquisitionErrorCode.BROWSER_LAUNCH_FAILED,
                    f"无法启动 Edge/Chrome：{last_err}",
                )
            try:
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                timeout_ms = int(config.nav_timeout * 1000)
                try:
                    resp = page.goto(url, wait_until=config.wait_until, timeout=timeout_ms)
                except PWTimeout as exc:
                    raise BrowserError(
                        AcquisitionErrorCode.BROWSER_NAVIGATION_FAILED,
                        f"导航超时：{exc}",
                    ) from exc

                # 需点击才触发下载的情形
                if config.download_click_selector:
                    try:
                        with page.expect_download(timeout=timeout_ms) as dl_info:
                            page.click(config.download_click_selector, timeout=timeout_ms)
                        download = dl_info.value
                        path = download.path()
                        with open(path, "rb") as fh:
                            body = fh.read()
                        return RawResponse(
                            status_code=200,
                            headers={},
                            body=body,
                            final_url=download.url,
                        )
                    except PWError as exc:
                        raise BrowserError(
                            AcquisitionErrorCode.BROWSER_DOWNLOAD_FAILED,
                            f"点击下载失败：{exc}",
                        ) from exc

                status = resp.status if resp is not None else 200
                headers = dict(resp.headers) if resp is not None else {}
                final_url = page.url
                content_type = "".join(
                    value for key, value in headers.items() if key.lower() == "content-type"
                ).lower()
                # Chromium's PDF viewer exposes an HTML shell through
                # ``page.content()``.  Preserve the original response bytes for
                # direct PDF URLs so the shared validator can see ``%PDF-`` and
                # the archive layer can store the actual document.
                if resp is not None and (
                    "pdf" in content_type
                    or final_url.lower().split("?", 1)[0].endswith(".pdf")
                ):
                    try:
                        # A PDF navigation is rendered by Chromium's internal
                        # viewer; ``resp.body()`` may therefore expose the
                        # viewer HTML shell instead of the document bytes.
                        # Fetch once through the same browser context so its
                        # cookies/session are retained while the raw response
                        # remains available to the shared validator.
                        raw = context.request.get(final_url, timeout=timeout_ms)
                        raw_headers = dict(raw.headers)
                        return RawResponse(
                            raw.status, raw_headers, raw.body(), raw.url,
                        )
                    except PWError:
                        try:
                            body = resp.body()
                        except PWError:
                            body = page.content().encode("utf-8")
                    return RawResponse(status, headers, body, final_url)
                # 无独立下载时，取渲染后页面内容
                body = page.content().encode("utf-8")
                return RawResponse(status, headers, body, final_url)
            finally:
                browser.close()
