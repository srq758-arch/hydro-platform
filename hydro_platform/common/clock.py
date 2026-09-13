"""统一时间源。

全系统禁止直接调用 datetime.now()，一律走这里。好处：
1. 统一 UTC + ISO8601 口径，避免本地时区污染入库时间戳；
2. 测试可通过 set_clock() 注入固定时间，保证结果可复现。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

# 默认时间源：带时区的 UTC now。测试可替换。
_now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def now() -> datetime:
    """返回当前时间（带 UTC 时区）。"""
    return _now_fn()


def now_iso() -> str:
    """返回当前时间的 ISO8601 字符串，用于入库时间戳字段。"""
    return now().isoformat()


def set_clock(fn: Callable[[], datetime]) -> None:
    """注入自定义时间源（仅测试使用）。"""
    global _now_fn
    _now_fn = fn


def reset_clock() -> None:
    """恢复默认 UTC 时间源。"""
    global _now_fn
    _now_fn = lambda: datetime.now(timezone.utc)
