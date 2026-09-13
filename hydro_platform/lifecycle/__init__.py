"""Lifecycle 层（文档 15/16）。

候选事实的事务性升级：只有「证据存在 + Validation 通过 + Review approve +
可标 publishable」四条件同时满足，才允许升级为正式 GenerationRecord 并进 Top100。
未复核/校验失败/缺证据的数据绝不进入正式排名（文档 15）。
"""

from __future__ import annotations

from .promotion import PromotionError, PromotionResult, promote_candidate

__all__ = ["PromotionError", "PromotionResult", "promote_candidate"]
