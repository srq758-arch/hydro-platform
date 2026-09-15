"""事务性升级测试（文档 15/16）。

验证四条件闸门：证据存在 + Validation 通过 + Review approve + 可标 publishable。
缺任一即拒绝写正式表；generation_gwh=None 拒绝；升级幂等；未复核数据不进 Top100。
"""

from __future__ import annotations

import pytest

from hydro_platform.common.enums import (
    GenerationMetric,
    MeasurementScope,
    NormalizedEnergyUnit,
    PeriodType,
    ValueType,
)
from hydro_platform.evidence import EvidenceStore
from hydro_platform.lifecycle import PromotionError, promote_candidate
from hydro_platform.models.candidate import ExtractionCandidate
from hydro_platform.validation import validate_candidate


def _seed_document(db, document_id="doc_1", content_hash="h1") -> None:
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
        source_id=None,
        task_id=None,
    )
    base.update(over)
    return ExtractionCandidate(**base)


def _save_evidence(db, cand) -> str:
    _seed_document(db)
    store = EvidenceStore(db)
    return store.save_for_candidate(cand, document_id="doc_1", content_hash="h1")


def test_clean_candidate_promotes(db):
    cand = _cand()
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    res = promote_candidate(
        db, cand, val, evidence_id=eid, review_approved=True, review_required=False
    )
    assert res.newly_created
    from hydro_platform.database.repositories import GenerationRepository

    repo = GenerationRepository(db)
    assert repo.count() == 1
    pub = repo.publishable(entity_id="e1")
    assert len(pub) == 1
    assert pub[0]["publication_status"] == "publishable"
    assert pub[0]["evidence_id"] == eid


def test_promotion_is_idempotent(db):
    cand = _cand()
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    r1 = promote_candidate(
        db, cand, val, evidence_id=eid, review_approved=True, review_required=False
    )
    r2 = promote_candidate(
        db, cand, val, evidence_id=eid, review_approved=True, review_required=False
    )
    assert r1.newly_created
    assert not r2.newly_created
    from hydro_platform.database.repositories import GenerationRepository

    assert GenerationRepository(db).count() == 1


def test_null_generation_rejected(db):
    cand = _cand(generation_gwh=None)
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    with pytest.raises(PromotionError, match="generation_gwh"):
        promote_candidate(
            db, cand, val, evidence_id=eid, review_approved=True, review_required=False
        )


def test_failed_validation_rejected(db):
    cand = _cand(value_type=ValueType.FORECAST)
    val = validate_candidate(cand)
    assert not val.passed
    eid = _save_evidence(db, cand)
    with pytest.raises(PromotionError, match="Validation"):
        promote_candidate(
            db, cand, val, evidence_id=eid, review_approved=True, review_required=True
        )


def test_review_required_but_not_approved_rejected(db):
    cand = _cand()
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    with pytest.raises(PromotionError, match="approve"):
        promote_candidate(
            db, cand, val, evidence_id=eid, review_approved=False, review_required=True
        )


def test_missing_evidence_id_rejected(db):
    cand = _cand()
    val = validate_candidate(cand)
    with pytest.raises(PromotionError, match="evidence"):
        promote_candidate(
            db, cand, val, evidence_id="", review_approved=True, review_required=False
        )


def test_unpersisted_evidence_rejected(db):
    cand = _cand()
    val = validate_candidate(cand)
    with pytest.raises(PromotionError, match="未落库"):
        promote_candidate(
            db,
            cand,
            val,
            evidence_id="ev_does_not_exist",
            review_approved=True,
            review_required=False,
        )


def test_missing_entity_id_rejected(db):
    cand = _cand(entity_id=None)
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    with pytest.raises(PromotionError, match="entity_id"):
        promote_candidate(
            db, cand, val, evidence_id=eid, review_approved=True, review_required=False
        )


def test_missing_value_type_is_not_defaulted_to_actual(db):
    cand = _cand(value_type=None)
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    with pytest.raises(PromotionError, match="value_type"):
        promote_candidate(
            db, cand, val, evidence_id=eid, review_approved=True, review_required=False
        )


def test_missing_scope_is_not_defaulted_to_plant(db):
    cand = _cand(measurement_scope=None)
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    with pytest.raises(PromotionError, match="measurement_scope"):
        promote_candidate(
            db, cand, val, evidence_id=eid, review_approved=True, review_required=False
        )


def test_missing_metric_cannot_be_approved_into_formal_records(db):
    cand = _cand(metric=None)
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    with pytest.raises(PromotionError, match="Validation|metric"):
        promote_candidate(
            db, cand, val, evidence_id=eid, review_approved=True, review_required=True
        )
    assert db.execute("SELECT COUNT(*) FROM generation_records").fetchone()[0] == 0


def test_missing_normalized_unit_cannot_be_approved_into_formal_records(db):
    cand = _cand(normalized_unit=None)
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    with pytest.raises(PromotionError, match="Validation|unit"):
        promote_candidate(
            db, cand, val, evidence_id=eid, review_approved=True, review_required=True
        )
    assert db.execute("SELECT COUNT(*) FROM generation_records").fetchone()[0] == 0


def test_approved_review_promotes(db):
    # 需复核且已 approve → 允许升级，review_status 记为 approved
    cand = _cand(confidence=0.4)  # 低置信 → 需复核
    val = validate_candidate(cand)
    eid = _save_evidence(db, cand)
    promote_candidate(
        db, cand, val, evidence_id=eid, review_approved=True, review_required=True
    )
    from hydro_platform.database.repositories import GenerationRepository

    row = GenerationRepository(db).get_by_key(
        entity_id="e1",
        period_type="calendar_year",
        period_label="2023",
        value_type="actual",
        measurement_scope="plant",
    )
    assert row["review_status"] == "approved"
    assert row["publication_status"] == "publishable"
