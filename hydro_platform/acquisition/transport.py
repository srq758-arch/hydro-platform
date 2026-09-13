"""网络传输抽象（文档 9.2）。

Transport 把「实际发一次 HTTP 请求」隔离成可注入接口：生产用 UrllibTransport
（标准库，无第三方依赖），测试注入假实现即可完全离线。HttpClient 只依赖此接口，
负责超时/重试/退避/校验等策略。
"""

from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol

from ..common.enums import AcquisitionErrorCode


@dataclass
class RawResponse:
    """一次传输的原始响应（未做业务校验）。"""

    status_code: int
    headers: dict[str, str]
    body: bytes
    final_url: str

    @property
    def content_type(self) -> str | None:
        # HTTP 头大小写不敏感
        for k, v in self.headers.items():
            if k.lower() == "content-type":
                return v
        return None


class TransportError(Exception):
    """传输层错误，携带归一化的错误分类码（文档 9.4）。"""

    def __init__(self, code: AcquisitionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class Transport(Protocol):
    """传输接口：给定 URL/头/超时，返回 RawResponse 或抛 TransportError。"""

    def fetch(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> RawResponse:  # pragma: no cover - 协议声明
        ...


class UrllibTransport:
    """基于标准库 urllib 的默认传输实现。

    只做单次请求 + 异常归一化；不含重试（重试由 HttpClient 负责，职责单一）。
    """

    def fetch(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> RawResponse:
        req = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                hdrs = {k: v for k, v in resp.headers.items()}
                return RawResponse(
                    status_code=getattr(resp, "status", 200) or 200,
                    headers=hdrs,
                    body=body,
                    final_url=resp.geturl(),
                )
        except urllib.error.HTTPError as exc:  # 有响应但状态码非 2xx
            body = b""
            try:
                body = exc.read()
            except Exception:  # noqa: BLE001 - 读失败不致命
                pass
            hdrs = {k: v for k, v in (exc.headers or {}).items()}
            return RawResponse(
                status_code=exc.code,
                headers=hdrs,
                body=body,
                final_url=exc.url or url,
            )
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLError) or isinstance(reason, ssl.CertificateError):
                raise TransportError(
                    AcquisitionErrorCode.CERTIFICATE_ERROR, f"证书错误：{reason}"
                ) from exc
            if isinstance(reason, socket.timeout) or isinstance(reason, TimeoutError):
                raise TransportError(
                    AcquisitionErrorCode.READ_TIMEOUT, f"读取超时：{reason}"
                ) from exc
            raise TransportError(
                AcquisitionErrorCode.NETWORK_ERROR, f"网络错误：{reason}"
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise TransportError(
                AcquisitionErrorCode.CONNECT_TIMEOUT, f"连接超时：{exc}"
            ) from exc
        except ssl.SSLError as exc:
            raise TransportError(
                AcquisitionErrorCode.CERTIFICATE_ERROR, f"SSL 错误：{exc}"
            ) from exc
        except OSError as exc:
            raise TransportError(
                AcquisitionErrorCode.NETWORK_ERROR, f"网络错误：{exc}"
            ) from exc
