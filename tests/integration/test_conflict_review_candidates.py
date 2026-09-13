"""同一事实键的不同候选必须分别保留并进入复核。"""

from hydro_platform.common.clock import now_iso
from hydro_platform.common.enums import Severity
from hydro_platform.common.result import ValidationResult
from hydro_platform.models.candidate import ExtractionCandidate
from hydro_platform.review.queue import ReviewQueue


def _candidate(db, candidate_id: str, value: float) -> ExtractionCandidate:
    now = now_iso()
    db.execute(
        "INSERT INTO stations(entity_id, canonical_name, country) VALUES ('conflict-station', 'Conflict', 'CN')",
    ) if db.execute("SELECT 1 FROM stations WHERE entity_id = 'conflict-station'").fetchone() is None else None
    db.execute(
        "INSERT OR IGNORE INTO sources(source_id, url, title) VALUES ('conflict-source', 'csv://conflict', 'Conflict')"
    )
    db.execute(
        """INSERT OR IGNORE INTO documents
        (document_id, source_id, original_url, content_kind, file_size, content_hash, local_path, created_at)
        VALUES (?, 'conflict-source', ?, 'csv', 1, ?, ?, ?)""",
        (f"doc-{candidate_id}", f"csv://{candidate_id}", f"hash-{candidate_id}", f"inline://{candidate_id}", now),
    )
    db.execute(
        """INSERT INTO extraction_candidates
        (candidate_id, entity_id, document_id, period_type, period_label, value_type,
         measurement_scope, generation_gwh, extracted_at)
        VALUES (?, 'conflict-station', ?, 'calendar_year', '2024', 'actual', 'plant', ?, ?)""",
        (candidate_id, f"doc-{candidate_id}", value, now),
    )
    return ExtractionCandidate(
        candidate_id=candidate_id,
        entity_id="conflict-station",
        period_type="calendar_year",
        period_label="2024",
        value_type="actual",
        measurement_scope="plant",
        generation_gwh=value,
        value_raw=str(value),
        unit_raw="GWh",
        source_id="conflict-source",
    )


def test_conflicting_candidates_get_separate_review_items(db):
    first = _candidate(db, "conflict-candidate-1", 100)
    second = _candidate(db, "conflict-candidate-2", 200)
    queue = ReviewQueue(db)
    validation = ValidationResult()
    validation.add_issue("DUPLICATE_RECORD", "same fact key", Severity.MEDIUM)

    first_review = queue.submit(first, validation, evidence_ids=[])
    second_review = queue.submit(second, validation, evidence_ids=[])
    db.commit()

    rows = db.execute(
        "SELECT review_id, candidate_id, fact_key, reason FROM review_items ORDER BY review_id"
    ).fetchall()
    assert first_review != second_review
    assert len(rows) == 2
    assert {row["candidate_id"] for row in rows} == {first.candidate_id, second.candidate_id}
    assert any("CONFLICT_CANDIDATE" in row["reason"] for row in rows)
