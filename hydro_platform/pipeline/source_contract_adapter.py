"""将旧来源对象/字典归一化为 B0 ``CandidateSource``。

这是 B1 的单向兼容边界：旧对象可以进入，输出只能是统一契约。适配器不访问
网络、不写数据库，也不根据 URL 猜测 PDF/HTML 类型。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..common.enums import CandidateSourceStatus, ContentKind
from ..models.source_pipeline import CandidateSource


def source_task_id(task: object) -> str:
    """取得真实 task_id；仅为旧测试对象生成稳定兼容 ID。"""
    task_id = getattr(task, "task_id", None)
    if task_id:
        return str(task_id)
    entity_id = getattr(task, "entity_id", "unknown")
    period = getattr(task, "target_period", "unknown")
    return f"legacy::{entity_id}::{period}"


def _value(source: object, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _content_kind(value: object) -> ContentKind:
    if isinstance(value, ContentKind):
        return value
    try:
        return ContentKind(str(value))
    except (TypeError, ValueError):
        return ContentKind.ANY


def _score(source: object) -> float:
    for key in ("combined_score", "priority_score", "source_reliability_score", "estimated_reliability"):
        value = _value(source, key)
        if value is not None:
            try:
                return max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
    return 0.0


def to_candidate_source(
    source: object,
    *,
    task_id: str,
    discovery_method: str | None = None,
    title: str | None = None,
    publisher: str | None = None,
) -> CandidateSource:
    """把一个旧 ref、搜索结果字典或 SourceCandidate 转为统一来源。"""
    if isinstance(source, CandidateSource):
        return source

    url = _value(source, "url") or _value(source, "source_url")
    canonical_url = _value(source, "canonical_url") or url
    method = discovery_method or _value(source, "discovery_method") or "legacy_adapter"
    expected = _value(source, "expected_content_kind")
    if expected is None:
        expected = _value(source, "expected", ContentKind.ANY)

    metadata: dict[str, Any] = {}
    if isinstance(source, Mapping):
        original_metadata = source.get("metadata")
        if isinstance(original_metadata, Mapping):
            metadata.update(original_metadata)
        known = {
            "url", "source_url", "canonical_url", "title", "publisher", "source_type",
            "discovery_method", "document_type", "expected", "expected_content_kind",
            "language", "combined_score", "priority_score", "source_reliability_score",
            "estimated_reliability", "lead_id", "metadata",
        }
        metadata.update({key: value for key, value in source.items() if key not in known})

    return CandidateSource(
        task_id=task_id,
        lead_id=_value(source, "lead_id"),
        url=str(url or ""),
        canonical_url=str(canonical_url or ""),
        title=title if title is not None else _value(source, "title"),
        publisher=publisher if publisher is not None else _value(source, "publisher"),
        source_type=str(_value(source, "source_type", "unknown") or "unknown"),
        discovery_method=str(method),
        # document_type remains descriptive metadata. It must not become a hard
        # acquisition expectation before content probing confirms the type.
        expected_content_kind=_content_kind(expected),
        language=_value(source, "language"),
        priority_score=_score(source),
        status=CandidateSourceStatus.ELIGIBLE,
        metadata=metadata,
    )


def normalize_candidate_sources(
    sources: Iterable[object],
    *,
    task_id: str,
    discovery_method: str | None = None,
) -> list[CandidateSource]:
    """归一化并按 canonical URL 去重；保留首次出现的评分顺序。"""
    normalized: list[CandidateSource] = []
    seen: set[str] = set()
    for source in sources:
        candidate = to_candidate_source(
            source,
            task_id=task_id,
            discovery_method=discovery_method,
        )
        key = candidate.canonical_url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized
