"""Evidence 保存与 Review 队列测试（文档 14/15）。

覆盖：证据幂等落库、证据 id 由内容派生、同事实同资料复用；复核触发条件
（校验失败/高危/低置信度/Top100）、幂等入队、决策记录、approve 判定。
"""

from __future__ import annotations

from hydro_platform.common.enums import (
    MeasurementScope,
    PeriodType,
    ReviewDecision,
    ValueType,
)
from hydro_platform.common.result import ValidationResult
from hydro_platform.evidence import EvidenceStore, build_evidence_for_candidate
from hydro_platform.models.candidate import ExtractionCandidate
from hydro_platform.models.evidence import Evidence, make_generation_fact_key
from hydro_platform.review import ReviewQueue, needs_review
from hydro_platform.validation import validate_candidate


def _seed_document(db, document_id: str, content_hash: str) -> None:
    """插入一条最小 documents 行，满足 evidence.document_id 外键（文档 14 证据不脱钩）。"""
    db.execute(
        "INSERT OR IGNORE INTO documents "
        "(document_id, original_url, file_size, content_hash, local_path, "
        " version, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
        (document_id, "http://x/doc", 10, content_hash, "raw/x", "2026-09-01T00:00:00Z"),
    )


def _cand(**over) -> ExtractionCandidate:
    base = dict(
        entity_id="e1",
        period_type=PeriodType.CALENDAR_YEAR,
        period_label="2023",
        generation_gwh=100.0,
        value_type=ValueType.ACTUAL,
        measurement_scope=MeasurementScope.PLANT,
        snippet="2023 年发电量 100 GWh",
        locator="p1",
        confidence=0.9,
        extractor="rule-v1",
        source_id=None,  # 本测聚焦证据存储本身；source FK 由集成测试覆盖
        task_id=None,
    )
    base.update(over)
    return ExtractionCandidate(**base)


# ---- Evidence ----

def test_evidence_id_is_content_derived():
    fk = make_generation_fact_key(
        entity_id="e1",
        period_type="calendar_year",
        period_label="2023",
        value_type="actual",
        measurement_scope="plant",
    )
    a = Evidence.derive_id(fact_type="generation", fact_key=fk, content_hash="h1")
    b = Evidence.derive_id(fact_type="generation", fact_key=fk, content_hash="h1")
    c = Evidence.derive_id(fact_type="generation", fact_key=fk, content_hash="h2")
    assert a == b
    assert a != c  # 内容(资料)不同 → 不同证据


def test_build_evidence_carries_locator_and_versions():
    ev = build_evidence_for_candidate(
        _cand(),
        document_id="doc_1",
        content_hash="h1",
        source_url="http://x/y",
        page_number=3,
        parser_version="parse-v1",
    )
    assert ev.document_id == "doc_1"
    assert ev.content_hash == "h1"
    assert ev.page_number == 3
    assert ev.snippet == "2023 年发电量 100 GWh"
    assert ev.locator == "p1"
    assert ev.extraction_version == "rule-v1"
    assert ev.parser_version == "parse-v1"


def test_evidence_store_is_idempotent(db):
    _seed_document(db, "doc_1", "h1")
    store = EvidenceStore(db)
    id1 = store.save_for_candidate(_cand(), document_id="doc_1", content_hash="h1")
    id2 = store.save_for_candidate(_cand(), document_id="doc_1", content_hash="h1")
    assert id1 == id2
    assert store.repo.count() == 1


def test_evidence_new_content_hash_new_row(db):
    _seed_document(db, "doc_1", "h1")
    _seed_document(db, "doc_2", "h2")
    store = EvidenceStore(db)
    store.save_for_candidate(_cand(), document_id="doc_1", content_hash="h1")
    store.save_for_candidate(_cand(), document_id="doc_2", content_hash="h2")
    assert store.repo.count() == 2


def test_evidence_persisted_fields(db):
    _seed_document(db, "doc_1", "h1")
    store = EvidenceStore(db)
    eid = store.save_for_candidate(
        _cand(), document_id="doc_1", content_hash="h1", source_url="http://x"
    )
    row = store.repo.get(eid)
    assert row is not None
    assert row["document_id"] == "doc_1"
    assert row["fact_type"] == "generation"
    assert row["created_at"] is not None


# ---- Review needs_review ----

def test_clean_candidate_no_review():
    cand = _cand()
    res = validate_candidate(cand)
    assert res.passed
    assert not needs_review(cand, res)


def test_failed_validation_needs_review():
    cand = _cand(value_type=ValueType.FORECAST)
    res = validate_candidate(cand)
    assert needs_review(cand, res)


def test_low_confidence_needs_review():
    cand = _cand(confidence=0.2)
    res = validate_candidate(cand)
    assert needs_review(cand, res)


def test_top100_always_needs_review():
    cand = _cand()
    res = validate_candidate(cand)
    assert res.passed
    assert needs_review(cand, res, is_top100=True)


# ---- ReviewQueue ----

def test_clean_candidate_not_enqueued(db):
    q = ReviewQueue(db)
    cand = _cand()
    res = validate_candidate(cand)
    assert q.submit(cand, res) is None
    assert q.repo.count() == 0


def test_flagged_candidate_enqueued(db):
    q = ReviewQueue(db)
    cand = _cand(value_type=ValueType.FORECAST)
    res = validate_candidate(cand)
    rid = q.submit(cand, res, evidence_ids=["ev_1"])
    assert rid is not None
    assert q.repo.count(status="open") == 1
    row = q.repo.get(rid)
    assert "ACTUAL_FORECAST_MIXED" in row["reason"]


def test_enqueue_is_idempotent_per_fact(db):
    q = ReviewQueue(db)
    cand = _cand(value_type=ValueType.FORECAST)
    res = validate_candidate(cand)
    r1 = q.submit(cand, res)
    r2 = q.submit(cand, res)
    assert r1 == r2
    assert q.repo.count() == 1


def test_decision_recorded_and_approved(db):
    q = ReviewQueue(db)
    cand = _cand(value_type=ValueType.FORECAST)
    res = validate_candidate(cand)
    rid = q.submit(cand, res)
    q.decide(rid, ReviewDecision.APPROVE, reviewer="alice")
    assert q.is_approved(rid)
    row = q.repo.get(rid)
    assert row["reviewer"] == "alice"
    assert row["resolved_at"] is not None


def test_reject_is_not_approved(db):
    q = ReviewQueue(db)
    cand = _cand(measurement_scope=MeasurementScope.REGION)
    res = validate_candidate(cand)
    rid = q.submit(cand, res)
    q.decide(rid, ReviewDecision.REJECT, reviewer="bob")
    assert not q.is_approved(rid)


def test_top100_clean_candidate_enqueued(db):
    q = ReviewQueue(db)
    cand = _cand()
    res = validate_candidate(cand)
    rid = q.submit(cand, res, is_top100=True)
    assert rid is not None
    row = q.repo.get(rid)
    assert "TOP100" in row["reason"] or row["reason"] == "REVIEW_REQUIRED"
