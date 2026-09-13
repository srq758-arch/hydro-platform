"""统一日志配置。

提供 get_logger()，模块内 `logger = get_logger(__name__)` 即可。
setup_logging() 在应用入口调用一次，配置格式与级别；库代码不应自行 basicConfig。
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """配置根日志器（应用入口调用一次，幂等）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """返回命名 logger。未显式 setup_logging 时也能安全使用。"""
    return logging.getLogger(name)
