"""兼容层：后台 Discovery 使用当前的 DeepSeek Responses 联网搜索。

历史版本曾在这里直接调用旧 Chat Completions 并传递一个非统一的搜索参数，
造成“智能任务”和后台任务使用两套不同的搜索实现。保留类名只为兼容
``DiscoveryResolver``，实际实现统一委托给 ``DeepSeekResponsesAgent``。
"""

from __future__ import annotations

import os
from typing import Any, Optional

from ..common.logging_setup import get_logger
from ..intelligence.deepseek_agent import DeepSeekAgentError, DeepSeekResponsesAgent, TaskIntent

logger = get_logger(__name__)


class DeepSeekSourceFinder:
    """旧调用点的轻量适配器，不再维护独立的搜索协议。"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash"
        self.enabled = bool(self.api_key)

    def find(self, task: dict[str, Any], max_candidates: int = 5) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        period = str(task.get("target_period") or "").strip()
        station_name = str(task.get("entity_name") or task.get("station_name") or "").strip()
        if not station_name or not period.isdigit() or len(period) != 4:
            return []
        intent = TaskIntent(
            station_name=station_name,
            target_period=period,
            period_type=str(task.get("period_type") or "calendar_year"),
            metric=str(task.get("metric") or "generation"),
            source_policy="official_or_authority",
            query_hints=tuple(str(item) for item in task.get("query_hints", []) if item)[:3],
        )
        station = {
            "entity_id": task.get("entity_id"), "canonical_name": station_name,
            "local_name": task.get("local_name"), "aliases": task.get("aliases"),
            "country": task.get("country"), "operator": task.get("operator"), "owner": task.get("owner"),
        }
        try:
            return DeepSeekResponsesAgent(api_key=self.api_key, model=self.model).search(
                intent=intent, station=station,
            )[:max_candidates]
        except DeepSeekAgentError as exc:
            logger.warning("DeepSeek Responses 搜索失败: %s", exc)
            return []
