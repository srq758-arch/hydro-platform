"""HTTP 客户端单测：超时/重试/退避/校验/哈希——用假 Transport，无网络。"""

from __future__ import annotations

import hashlib

from hydro_platform.common.enums import AccessMethod, AcquisitionErrorCode, ContentKind
from hydro_platform.acquisition.http_client import HttpClient, HttpClientConfig
from hydro_platform.acquisition.transport import RawResponse, TransportError

PDF_BODY = b"%PDF-1.7\n" + b"data" * 100
HTML_BODY = b"<!DOCTYPE html><html><body>hi</body></html>"


class ScriptedTransport:
    """按预设脚本依次返回 RawResponse 或抛 TransportError，记录调用次数。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def fetch(self, url, *, headers, timeout):
        self.calls += 1
        item = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def _resp(status=200, ct="application/pdf", body=PDF_BODY, final=None):
    return RawResponse(
        status_code=status,
        headers={"Content-Type": ct},
        body=body,
        final_url=final or "https://example.org/final.pdf",
    )


def _client(transport, **cfg):
    sleeps = []
    c = HttpClient(
        transport=transport,
        config=HttpClientConfig(**cfg),
        sleep=lambda s: sleeps.append(s),
    )
    return c, sleeps


def test_fetch_success_builds_meta_and_hash():
    t = ScriptedTransport([_resp()])
    client, _ = _client(t)
    res = client.fetch("https://example.org/x.pdf", expected=ContentKind.PDF)
    assert res.success
    assert res.attempts == 1
    assert res.body == PDF_BODY
    assert res.meta is not None
    assert res.meta.content_kind == ContentKind.PDF
    assert res.meta.final_url == "https://example.org/final.pdf"
    assert res.meta.file_size == len(PDF_BODY)
    assert res.meta.content_hash == hashlib.sha256(PDF_BODY).hexdigest()
    assert res.meta.access_method == AccessMethod.HTTP
    assert res.meta.fetched_at  # 有时间戳


def test_retry_then_success_with_backoff():
    # 前两次超时，第三次成功
    t = ScriptedTransport([
        TransportError(AcquisitionErrorCode.READ_TIMEOUT, "t1"),
        TransportError(AcquisitionErrorCode.READ_TIMEOUT, "t2"),
        _resp(),
    ])
    client, sleeps = _client(t, max_attempts=3, backoff_base=0.5, backoff_factor=2.0)
    res = client.fetch("https://example.org/x.pdf", expected=ContentKind.PDF)
    assert res.success
    assert res.attempts == 3
    assert t.calls == 3
    # 指数退避：0.5 * 2^0, 0.5 * 2^1
    assert sleeps == [0.5, 1.0]


def test_retryable_exhausts_attempts():
    t = ScriptedTransport([TransportError(AcquisitionErrorCode.NETWORK_ERROR, "down")])
    client, sleeps = _client(t, max_attempts=3)
    res = client.fetch("https://example.org/x.pdf")
    assert not res.success
    assert res.error_code == AcquisitionErrorCode.NETWORK_ERROR
    assert res.attempts == 3
    assert t.calls == 3
    assert len(sleeps) == 2  # 两次失败后各退避一次，最后一次不再睡


def test_non_retryable_stops_immediately():
    # 404 是确定性失败，不应重试
    t = ScriptedTransport([_resp(status=404, ct="text/html", body=HTML_BODY)])
    client, sleeps = _client(t, max_attempts=3)
    res = client.fetch("https://example.org/missing.pdf", expected=ContentKind.PDF)
    assert not res.success
    assert res.error_code == AcquisitionErrorCode.HTTP_404
    assert t.calls == 1
    assert sleeps == []


def test_block_page_not_retried_but_meta_kept():
    block = (
        b"<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
        b"<body>captcha verifying you are human</body></html>"
    )
    t = ScriptedTransport([_resp(status=200, ct="text/html", body=block)])
    client, _ = _client(t, max_attempts=3)
    res = client.fetch("https://example.org/x.pdf", expected=ContentKind.PDF)
    assert not res.success
    assert res.error_code == AcquisitionErrorCode.HTML_BLOCK_PAGE
    assert res.meta is not None  # 失败也保留 meta 以便归档/诊断
    assert t.calls == 1


def test_429_is_retried():
    t = ScriptedTransport([
        _resp(status=429, ct="text/html", body=HTML_BODY),
        _resp(),
    ])
    client, sleeps = _client(t, max_attempts=3)
    res = client.fetch("https://example.org/x.pdf", expected=ContentKind.PDF)
    assert res.success
    assert res.attempts == 2
    assert len(sleeps) == 1
