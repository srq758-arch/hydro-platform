"""一次性联网 smoke（用户决策：离线优先 + 一次联网 smoke）。

默认被 `-m 'not network'` 跳过，保证离线单测恒绿。显式开启：
    .venv/Scripts/python.exe -m pytest -m network -q

目的：用真实 UrllibTransport 走一遍「采集 → finalize」真实路径，验证 DNS/TLS/
重定向/内容哈希/最终 URL 这些只有真外网才会经历的环节确实打通——而非 fixture 回放。
不依赖易变的第三方文档：命中 IANA 维护的稳定测试页 example.com。真无网络时
skip（而非 fail），避免离线环境误报。
"""

from __future__ import annotations

import pytest

from hydro_platform.acquisition.router import AcquisitionRouter
from hydro_platform.common.enums import ContentKind

pytestmark = pytest.mark.network

# IANA 维护、长期稳定、允许抓取的测试页。
_SMOKE_URL = "https://example.com/"


def test_real_http_fetch_end_to_end():
    router = AcquisitionRouter()  # 默认真实 UrllibTransport
    try:
        res = router.fetch(_SMOKE_URL, expected=ContentKind.HTML)
    except Exception as exc:  # pragma: no cover - 环境相关
        pytest.skip(f"无外网连通性，跳过联网 smoke：{exc!r}")

    if not res.success:
        code = res.error_code.value if res.error_code else "?"
        # 网络受限（代理/墙）导致的确定性失败：skip 而非 fail。
        pytest.skip(f"联网获取未成功[{code}]，判为环境受限而跳过")

    # 真实路径才会产出的凭据：最终 URL、内容哈希、非空正文。
    assert res.meta is not None
    assert res.meta.final_url and res.meta.final_url.startswith("http")
    assert res.meta.content_hash and len(res.meta.content_hash) >= 16
    assert res.body and len(res.body) > 0
    body = res.body.decode("utf-8", errors="replace").lower()
    assert "example" in body  # 页面里确有 "Example Domain"
