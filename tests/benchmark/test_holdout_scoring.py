"""Holdout 评分门测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from holdout_scoring import score_holdout  # noqa: E402


def _result(case_id, *urls):
    return {"case_id": case_id, "qualified": [{"url": url} for url in urls]}


def _annotation(case_id, status, *gold):
    return {"case_id": case_id, "label_status": status, "gold_candidate_urls": list(gold)}


def test_unreviewed_cases_do_not_enter_metrics_or_open_gate():
    score = score_holdout(
        [_result("hit", "https://official.test/report.pdf"), _result("pending")],
        [
            _annotation("hit", "confirmed_hit", "https://official.test/report.pdf"),
            _annotation("pending", "not_reviewed"),
        ],
    )

    assert score.reviewed_cases == 1
    assert score.recall == 1.0
    assert score.gate_open is False


def test_confirmed_no_hit_qualified_candidate_counts_as_false_positive():
    score = score_holdout(
        [_result("no_hit", "https://wrong.test/page")],
        [_annotation("no_hit", "confirmed_no_hit")],
    )

    assert score.confirmed_no_hit_cases == 1
    assert score.false_positive_candidates == 1
    assert score.precision == 0.0
    assert score.gate_open is True


def test_confirmed_hit_requires_gold_url():
    with pytest.raises(ValueError, match="gold_candidate_urls"):
        score_holdout(
            [_result("hit", "https://official.test/report.pdf")],
            [_annotation("hit", "confirmed_hit")],
        )


def test_duplicate_or_missing_case_ids_are_rejected():
    with pytest.raises(ValueError, match="case_id"):
        score_holdout(
            [_result("same"), _result("same")],
            [_annotation("same", "not_reviewed")],
        )
