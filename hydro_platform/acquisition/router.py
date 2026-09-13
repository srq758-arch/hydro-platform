"""Acquisition 路由（文档 9.1）。

默认策略：HTTP/API 优先；当 HTTP 因需要 JavaScript/被拦截/被拒绝而失败时，
回退到 Playwright 浏览器访问（第 6 步实装）。本期若无浏览器客户端，回退不可用
时如实返回 HTTP 的失败结果，不静默成功。

支持本地文件：file:// 协议的 URL 通过 LocalFileRouter 处理。
"""

from __future__ import annotations

from typing import Protocol

from ..common.enums import AccessMethod, AcquisitionErrorCode, ContentKind
from ..common.logging_setup import get_logger
from .http_client import HttpClient
from .result import FetchResult

logger = get_logger(__name__)

# HTTP 失败后值得改用浏览器重试的错误码：多为反爬/需 JS/被拒。
_BROWSER_FALLBACK_CODES = frozenset({
    AcquisitionErrorCode.HTTP_403,
    AcquisitionErrorCode.HTTP_429,
    AcquisitionErrorCode.HTML_BLOCK_PAGE,
    AcquisitionErrorCode.NOT_PDF,           # 往往是 JS 渲染后才出下载
    AcquisitionErrorCode.NOT_EXPECTED_TYPE,
})


class BrowserClient(Protocol):
    """浏览器客户端接口（第 6 步 Playwright 实装）。"""

    def fetch(
        self,
        url: str,
        *,
        expected: ContentKind = ContentKind.ANY,
    ) -> FetchResult:  # pragma: no cover - 协议声明
        ...


class AcquisitionRouter:
    """按策略选择 HTTP/API 或浏览器获取。支持本地文件（file:// 协议）。"""

    def __init__(
        self,
        http_client: HttpClient | None = None,
        browser_client: BrowserClient | None = None,
    ) -> None:
        self.http = http_client or HttpClient()
        self.browser = browser_client

    def fetch(
        self,
        url: str,
        *,
        expected: ContentKind = ContentKind.ANY,
        access_method: AccessMethod = AccessMethod.HTTP,
        allow_browser_fallback: bool = True,
    ) -> FetchResult:
        """获取 url。支持 file:// 协议（本地文件）。HTTP 失败且属可回退错误时，尝试浏览器（若可用）。"""
        # 本地文件：使用 LocalFileRouter
        if url.startswith("file://"):
            from .local_router import LocalFileRouter
            local_router = LocalFileRouter()
            # 去掉 file:// 前缀，提取实际路径
            file_path = url[7:]  # "file:///path/to/file" -> "/path/to/file"
            return local_router.fetch(file_path, expected=expected)

        # HTTP/HTTPS：使用 HttpClient
        result = self.http.fetch(url, expected=expected, access_method=access_method)
        if result.success:
            return result

        if not (allow_browser_fallback and result.error_code in _BROWSER_FALLBACK_CODES):
            return result

        if self.browser is None:
            logger.info(
                "HTTP 失败[%s] 且无浏览器客户端可回退：%s",
                result.error_code.value if result.error_code else "?", url,
            )
            return result

        logger.info("HTTP 失败[%s]，回退浏览器：%s",
                    result.error_code.value if result.error_code else "?", url)
        return self.browser.fetch(url, expected=expected)
