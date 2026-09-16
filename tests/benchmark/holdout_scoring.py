"""Holdout 揭示结果评分。

盲测输入与揭示标注分离：只有人工标注为 ``confirmed_hit`` 或
``confirmed_no_hit`` 的案例进入指标；未标注案例不会被当成负例，也不会让
50 条 seedlist 批次错误放行。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Iterable


REVIEWED_STATUSES = frozenset({"confirmed_hit", "confirmed_no_hit"})
VALID_STATUSES = REVIEWED_STATUSES | frozenset({"needs_more_search", "not_reviewed"})


def _canonical_url(value: Any) -> str:
    """只做稳定的 URL 比较规范化，不改变报告中的原始 URL。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


@dataclass(frozen=True)
class HoldoutScore:
    total_cases: int
    reviewed_cases: int
    confirmed_hit_cases: int
    confirmed_no_hit_cases: int
    matched_hit_cases: int
    qualified_candidates: int
    matched_candidates: int
    false_positive_candidates: int
    recall: float | None
    precision: float | None
    gate_open: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_holdout(
    discovery_results: Iterable[dict[str, Any]],
    annotations: Iterable[dict[str, Any]],
) -> HoldoutScore:
    """根据发现结果和独立揭示标注计算 Holdout 指标。"""
    discovery_rows = list(discovery_results)
    results_by_id = {str(item.get("case_id")): item for item in discovery_rows}
    annotation_rows = list(annotations)
    if len(results_by_id) != len(discovery_rows):
        # 重复 case_id 会让一个结果覆盖另一个，必须显式失败。
        raise ValueError("discovery_results 必须是无重复 case_id 的列表")
    if len(results_by_id) != len(annotation_rows):
        raise ValueError("发现结果与揭示标注的案例数量不一致")

    reviewed = hit_cases = matched_hit_cases = 0
    no_hit_cases = 0
    qualified_count = matched_count = 0
    for annotation in annotation_rows:
        case_id = str(annotation.get("case_id") or "")
        status = str(annotation.get("label_status") or "")
        if status not in VALID_STATUSES:
            raise ValueError(f"{case_id}: 非法 label_status={status!r}")
        if case_id not in results_by_id:
            raise ValueError(f"{case_id}: 缺少发现结果")
        if status not in REVIEWED_STATUSES:
            continue

        reviewed += 1
        result = results_by_id[case_id]
        qualified = result.get("qualified") or []
        qualified_urls = [_canonical_url(item.get("url")) for item in qualified if isinstance(item, dict)]
        qualified_urls = [url for url in qualified_urls if url]
        gold_urls = {
            _canonical_url(url)
            for url in (annotation.get("gold_candidate_urls") or [])
            if _canonical_url(url)
        }
        if status == "confirmed_hit":
            if not gold_urls:
                raise ValueError(f"{case_id}: confirmed_hit 必须提供 gold_candidate_urls")
            hit_cases += 1
        else:
            no_hit_cases += 1

        qualified_count += len(qualified_urls)
        case_matches = sum(url in gold_urls for url in qualified_urls)
        matched_count += case_matches
        if status == "confirmed_hit" and case_matches:
            matched_hit_cases += 1

    return HoldoutScore(
        total_cases=len(annotation_rows),
        reviewed_cases=reviewed,
        confirmed_hit_cases=hit_cases,
        confirmed_no_hit_cases=no_hit_cases,
        matched_hit_cases=matched_hit_cases,
        qualified_candidates=qualified_count,
        matched_candidates=matched_count,
        false_positive_candidates=qualified_count - matched_count,
        recall=(matched_hit_cases / hit_cases) if hit_cases else None,
        precision=(matched_count / qualified_count) if qualified_count else None,
        gate_open=reviewed == len(annotation_rows),
    )


def score_holdout_files(discovery_path: Path, annotation_path: Path) -> HoldoutScore:
    """从 JSON 文件读取并评分，供批次验收脚本调用。"""
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    annotations = json.loads(annotation_path.read_text(encoding="utf-8"))
    if not isinstance(discovery, list) or not isinstance(annotations, list):
        raise ValueError("Holdout JSON 根节点必须是数组")
    return score_holdout(discovery, annotations)
