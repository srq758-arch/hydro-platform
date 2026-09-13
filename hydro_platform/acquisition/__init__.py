"""Acquisition 访问层（文档 9）。

职责：按路由用 HTTP/API（本期）或 Playwright（后续）获取原始资料，并对
下载结果做合法性判断——不只看 HTTP 200，还要看 Content-Type、大小、最终 URL
与文件魔数（文档 9.4）。产出统一的 FetchResult 供 Archive 层归档。

网络访问通过可注入的 Transport 抽象，默认基于标准库 urllib，便于离线测试。
"""

from .result import DownloadMeta, FetchResult
from .validators import (
    detect_content_kind,
    is_html_block_page,
    looks_like_html,
    looks_like_pdf,
    validate_download,
)
from .transport import RawResponse, Transport, TransportError, UrllibTransport
from .finalize import build_meta, finalize_response
from .http_client import DEFAULT_USER_AGENT, HttpClient, HttpClientConfig
from .browser_client import (
    BROWSER_PRIORITY,
    BrowserConfig,
    BrowserDriver,
    BrowserError,
    PlaywrightBrowserClient,
    create_browser_client,
    playwright_available,
)
from .router import AcquisitionRouter

__all__ = [
    "DownloadMeta",
    "FetchResult",
    "detect_content_kind",
    "is_html_block_page",
    "looks_like_html",
    "looks_like_pdf",
    "validate_download",
    "RawResponse",
    "Transport",
    "TransportError",
    "UrllibTransport",
    "build_meta",
    "finalize_response",
    "DEFAULT_USER_AGENT",
    "HttpClient",
    "HttpClientConfig",
    "BROWSER_PRIORITY",
    "BrowserConfig",
    "BrowserDriver",
    "BrowserError",
    "PlaywrightBrowserClient",
    "create_browser_client",
    "playwright_available",
    "AcquisitionRouter",
]
