"""共享收尾逻辑：把一次原始响应校验并归一成 FetchResult。

HTTP 客户端与浏览器客户端都调用这里，确保「下载合法性判断 + 元数据/哈希」
只有一套实现（文档 9.4 / 10.3），不会因客户端不同而口径漂移。
"""

from __future__ import annotations

import hashlib

from ..common.clock import now_iso
from ..common.enums import AccessMethod, ContentKind
from .result import DownloadMeta, FetchResult
from .transport import RawResponse
from .validators import validate_download


def build_meta(
    original_url: str,
    resp: RawResponse,
    kind: ContentKind,
    access_method: AccessMethod,
    elapsed_ms: int | None,
) -> DownloadMeta:
    """据响应构建文档元数据（含 sha256 内容哈希）。"""
    return DownloadMeta(
        original_url=original_url,
        final_url=resp.final_url,
        status_code=resp.status_code,
        content_type=resp.content_type,
        file_size=len(resp.body),
        content_hash=hashlib.sha256(resp.body).hexdigest(),
        content_kind=kind,
        access_method=access_method,
        fetched_at=now_iso(),
        elapsed_ms=elapsed_ms,
    )


def finalize_response(
    original_url: str,
    resp: RawResponse,
    *,
    expected: ContentKind,
    access_method: AccessMethod,
    max_bytes: int | None,
    elapsed_ms: int | None = None,
    attempts: int = 1,
) -> FetchResult:
    """校验响应并返回 FetchResult。失败也带上 meta 以便归档/诊断。"""
    err_code, kind = validate_download(
        status_code=resp.status_code,
        content_type=resp.content_type,
        body=resp.body,
        expected=expected,
        max_bytes=max_bytes,
    )
    meta = build_meta(original_url, resp, kind, access_method, elapsed_ms)
    if err_code is None:
        return FetchResult.ok(meta=meta, body=resp.body, attempts=attempts)
    message = f"下载不合法：{err_code.value}"
    if err_code.value == "NOT_PDF" and kind == ContentKind.HTML:
        message += "（实际返回 HTML 页面，浏览器回退也未取得 PDF）"
    return FetchResult.fail(err_code, message, meta=meta, attempts=attempts)
