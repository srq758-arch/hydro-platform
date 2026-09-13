"""HTTP/API 获取客户端（文档 9.2 / 9.4）。

在 Transport 之上实现：超时、有限重试、指数退避、User-Agent、Content-Type 检查、
最终 URL 记录、文件大小限制、内容哈希、HTML 拦截页检测。API 与 HTTP 共用同一
GET 通道，差异仅在期望内容类型（JSON vs 文件/HTML）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..common.enums import AccessMethod, AcquisitionErrorCode, ContentKind
from ..common.logging_setup import get_logger
from .finalize import finalize_response
from .result import FetchResult
from .transport import RawResponse, Transport, TransportError, UrllibTransport

logger = get_logger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HydroPlatform/1.0 "
    "(+data-collection; contact via project settings)"
)

# 可重试的错误码：瞬时网络/超时/限流/5xx。403/404/NOT_PDF 等属确定性失败，不重试。
_RETRYABLE = frozenset({
    AcquisitionErrorCode.NETWORK_ERROR,
    AcquisitionErrorCode.CONNECT_TIMEOUT,
    AcquisitionErrorCode.READ_TIMEOUT,
    AcquisitionErrorCode.HTTP_429,
    AcquisitionErrorCode.HTTP_ERROR,  # 含 5xx；4xx 已被更精确的码拦截
})


@dataclass
class HttpClientConfig:
    """HTTP 客户端策略参数。"""

    timeout: float = 30.0
    max_attempts: int = 3          # 总尝试次数（含首次）
    backoff_base: float = 0.5      # 退避基数（秒）
    backoff_factor: float = 2.0    # 指数底
    max_bytes: int = 100 * 1024 * 1024  # 单文件大小上限，默认 100MB
    user_agent: str = DEFAULT_USER_AGENT
    extra_headers: dict[str, str] = field(default_factory=dict)


def _is_retryable(code: AcquisitionErrorCode) -> bool:
    return code in _RETRYABLE


class HttpClient:
    """带重试/退避与下载校验的 GET 客户端。"""

    def __init__(
        self,
        transport: Transport | None = None,
        config: HttpClientConfig | None = None,
        *,
        sleep=time.sleep,
    ) -> None:
        self.transport = transport or UrllibTransport()
        self.config = config or HttpClientConfig()
        self._sleep = sleep  # 可注入，测试不必真的睡

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.config.user_agent}
        headers.update(self.config.extra_headers)
        return headers

    def _backoff(self, attempt_index: int) -> float:
        # attempt_index 从 0 开始（首次失败后 sleep 用 index 0）
        return self.config.backoff_base * (self.config.backoff_factor ** attempt_index)

    def fetch(
        self,
        url: str,
        *,
        expected: ContentKind = ContentKind.ANY,
        access_method: AccessMethod = AccessMethod.HTTP,
    ) -> FetchResult:
        """获取 url 并校验。失败自动重试（仅瞬时错误），返回统一 FetchResult。"""
        cfg = self.config
        last_code = AcquisitionErrorCode.NETWORK_ERROR
        last_msg = "未执行"
        last_resp: RawResponse | None = None

        for attempt in range(cfg.max_attempts):
            started = time.perf_counter()
            try:
                resp = self.transport.fetch(url, headers=self._headers(), timeout=cfg.timeout)
            except TransportError as exc:
                last_code, last_msg, last_resp = exc.code, str(exc), None
                logger.warning("获取失败[%s] %s（第 %d 次）", exc.code.value, url, attempt + 1)
                if _is_retryable(exc.code) and attempt + 1 < cfg.max_attempts:
                    self._sleep(self._backoff(attempt))
                    continue
                return FetchResult.fail(exc.code, last_msg, attempts=attempt + 1)

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            result = finalize_response(
                url, resp,
                expected=expected,
                access_method=access_method,
                max_bytes=cfg.max_bytes,
                elapsed_ms=elapsed_ms,
                attempts=attempt + 1,
            )
            if result.success:
                logger.info(
                    "获取成功 %s → %s（%s, %d bytes）",
                    url, resp.final_url, result.meta.content_kind.value, result.meta.file_size,
                )
                return result

            err_code = result.error_code
            last_code, last_msg, last_resp = err_code, result.error, resp
            logger.warning("下载不合法[%s] %s（第 %d 次）", err_code.value, url, attempt + 1)
            if _is_retryable(err_code) and attempt + 1 < cfg.max_attempts:
                self._sleep(self._backoff(attempt))
                continue
            return result

        # 理论不可达（循环内都会 return），兜底
        return FetchResult.fail(last_code, last_msg, attempts=cfg.max_attempts)
