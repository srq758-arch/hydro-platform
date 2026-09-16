"""LLM 抽取执行（文档 12.2）。

流程：构造 prompt → 调 provider → 解析并校验 JSON（容错去除 ```json 围栏）→
转成 ExtractionCandidate 列表。解析失败返回空列表并记日志，绝不把非法输出当事实。
"""

from __future__ import annotations

import json
import re

from ...common.logging_setup import get_logger
from ...models.candidate import ExtractionCandidate
from .prompts import build_extraction_prompt
from .provider import LLMProvider
from .schema import LLMExtractionOutput

logger = get_logger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    """去掉 LLM 常见的 ```json ... ``` 代码围栏。"""
    return _FENCE_RE.sub("", text or "").strip()


def _extract_json_object(text: str) -> str | None:
    """从文本里截出第一个花括号 JSON 对象（容忍前后噪声）。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def llm_extract(
    content: str,
    provider: LLMProvider,
    *,
    entity_id: str | None = None,
    entity_name: str | None = None,
    target_period: str | None = None,
    period_type: str = "calendar_year",
    task_id: str | None = None,
    source_id: str | None = None,
    locator: str | None = "llm",
) -> list[ExtractionCandidate]:
    """用 LLM 从文本抽取候选。非法/空输出返回 []，不抛异常。"""
    if not content:
        return []
    system, user = build_extraction_prompt(
        content, entity_name=entity_name, target_period=target_period, period_type=period_type
    )
    resp = provider.complete(system=system, user=user)

    raw = _strip_fences(resp.text)
    payload = _extract_json_object(raw)
    if payload is None:
        logger.warning("LLM 输出无 JSON 对象，丢弃")
        return []
    try:
        data = json.loads(payload)
        output = LLMExtractionOutput.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("LLM 输出解析/校验失败，丢弃：%s", exc)
        return []

    return [
        c.to_candidate(
            entity_id=entity_id, task_id=task_id, source_id=source_id, locator=locator
        )
        for c in output.candidates
    ]
