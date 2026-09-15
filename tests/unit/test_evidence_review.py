"""Evidence 保存与 Review 队列测试（文档 14/15）。

覆盖：证据幂等落库、证据 id 由内容派生、同事实同资料复用；复核触发条件
（校验失败/高危/低置信度/Top100）、幂等入队、决策记录、approve 判定。
"""

from __future__ import annotations

import hashlib
import json

import pytest

from hydro_platform.common.enums import (
    GenerationMetric,
    MeasurementScope,
    NormalizedEnergyUnit,
    PeriodType,
    ReviewDecision,
    ValueType,
)
from hydro_platform.common.result import ValidationResult
from hydro_platform.evidence import EvidenceStore, build_evidence_for_candidate
from hydro_platform.models.candidate import ExtractionCandidate
from hydro_platform.models.evidence import Evidence, make_generation_fact_key
from hydro_platform.review import ReviewQueue, needs_review
from hydro_platform.database.repositories import ReviewTransitionError
from hydro_platform.validation import validate_candidate
from hydro_platform.pipeline.candidate_evidence_binding import create_candidate_with_evidence


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
        metric=GenerationMetric.GROSS_GENERATION,
        normalized_unit=NormalizedEnergyUnit.GWH,
        unit_raw="GWh",
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


def _persist_review_candidate(db, cand: ExtractionCandidate) -> list[str]:
    """Persist the same Candidate→Evidence→Document chain used in production."""
    db.execute(
        "INSERT OR IGNORE INTO stations (entity_id, canonical_name, country) VALUES (?, ?, ?)",
        (cand.entity_id, "Evidence Queue Test Station", "Test"),
    )
    canonical = json.dumps(
        cand.model_dump(mode="json", exclude={"candidate_id"}),
        sort_keys=True,
        ensure_ascii=False,
    )
    suffix = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    document_id = f"doc_{suffix}"
    content_hash = f"hash_{suffix}"
    _seed_document(db, document_id, content_hash)
    evidence_id = EvidenceStore(db).save_for_candidate(
        cand,
        document_id=document_id,
        content_hash=content_hash,
        source_url="http://x/doc",
    )
    cand.candidate_id = f"cand_{suffix}"
    create_candidate_with_evidence(
        conn=db,
        candidate_id=cand.candidate_id,
        task_id=cand.task_id,
        entity_id=cand.entity_id,
        document_id=document_id,
        evidence_ids=[evidence_id],
        period_type=cand.period_type,
        period_label=cand.period_label,
        value_type=cand.value_type,
        measurement_scope=cand.measurement_scope,
        generation_gwh=cand.generation_gwh,
        value_raw=cand.value_raw,
        unit_raw=cand.unit_raw,
        snippet=cand.snippet,
        extraction_method=cand.extractor,
    )
    return [evidence_id]


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


def test_build_evidence_infers_page_and_table_from_structured_locator():
    cand = _cand()
    cand.locator = "page[2].table[1].row[3].col[4]"
    ev = build_evidence_for_candidate(cand, content_hash="h1")
    assert ev.page_number == 2
    assert ev.table_reference == "table[1].row[3].col[4]"


def test_build_evidence_infers_ocr_page_from_locator():
    cand = _cand()
    cand.locator = "page[7].ocr"
    ev = build_evidence_for_candidate(cand, content_hash="h1")
    assert ev.page_number == 7
    assert ev.table_reference is None


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


def test_ocr_derived_candidate_always_needs_review():
    cand = _cand()
    cand.flags.append("OCR_DERIVED")
    res = validate_candidate(cand)
    assert res.passed
    assert needs_review(cand, res)


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
    evidence_ids = _persist_review_candidate(db, cand)
    rid = q.submit(cand, res, evidence_ids=evidence_ids)
    assert rid is not None
    assert q.repo.count(status="open") == 1
    row = q.repo.get(rid)
    assert "ACTUAL_FORECAST_MIXED" in row["reason"]


def test_review_payload_preserves_evidence_metadata(db):
    q = ReviewQueue(db)
    cand = _cand(value_type=ValueType.FORECAST)
    res = validate_candidate(cand)
    evidence_ids = _persist_review_candidate(db, cand)
    rid = q.submit(
        cand,
        res,
        evidence_ids=evidence_ids,
        evidence_metadata={
            "ocr": {
                "page_number": 2,
                "engine": "fake-ocr",
                "source_image_sha256": "abc123",
            }
        },
    )
    payload = json.loads(q.repo.get(rid)["payload"])
    assert payload["evidence_metadata"]["ocr"]["page_number"] == 2
    assert payload["evidence_metadata"]["ocr"]["engine"] == "fake-ocr"


def test_enqueue_is_idempotent_per_fact(db):
    q = ReviewQueue(db)
    cand = _cand(value_type=ValueType.FORECAST)
    res = validate_candidate(cand)
    evidence_ids = _persist_review_candidate(db, cand)
    r1 = q.submit(cand, res, evidence_ids=evidence_ids)
    r2 = q.submit(cand, res, evidence_ids=evidence_ids)
    assert r1 == r2
    assert q.repo.count() == 1


def test_decision_recorded_and_approved(db):
    q = ReviewQueue(db)
    cand = _cand(value_type=ValueType.FORECAST)
    res = validate_candidate(cand)
    evidence_ids = _persist_review_candidate(db, cand)
    rid = q.submit(cand, res, evidence_ids=evidence_ids)
    q.decide(rid, ReviewDecision.APPROVE, reviewer="alice")
    assert q.is_approved(rid)
    row = q.repo.get(rid)
    assert row["reviewer"] == "alice"
    assert row["resolved_at"] is not None


def test_review_decision_cannot_be_repeated(db):
    q = ReviewQueue(db)
    cand = _cand(value_type=ValueType.FORECAST)
    res = validate_candidate(cand)
    evidence_ids = _persist_review_candidate(db, cand)
    rid = q.submit(cand, res, evidence_ids=evidence_ids)
    q.decide(rid, ReviewDecision.APPROVE, reviewer="alice")

    with pytest.raises(ReviewTransitionError, match="非法复核状态转换"):
        q.decide(rid, ReviewDecision.REJECT, reviewer="bob")
    assert q.repo.get(rid)["status"] == "approve"


def test_reject_is_not_approved(db):
    q = ReviewQueue(db)
    cand = _cand(measurement_scope=MeasurementScope.REGION)
    res = validate_candidate(cand)
    evidence_ids = _persist_review_candidate(db, cand)
    rid = q.submit(cand, res, evidence_ids=evidence_ids)
    q.decide(rid, ReviewDecision.REJECT, reviewer="bob")
    assert not q.is_approved(rid)


def test_top100_clean_candidate_enqueued(db):
    q = ReviewQueue(db)
    cand = _cand()
    res = validate_candidate(cand)
    evidence_ids = _persist_review_candidate(db, cand)
    rid = q.submit(cand, res, evidence_ids=evidence_ids, is_top100=True)
    assert rid is not None
    row = q.repo.get(rid)
    assert "TOP100" in row["reason"] or row["reason"] == "REVIEW_REQUIRED"
