"""SourceAttempt 台账使用短事务记录每个来源的独立结果。"""

from hydro_platform.common.enums import CandidateSourceStatus, ContentKind
from hydro_platform.models.source_pipeline import CandidateSource
from hydro_platform.pipeline.source_attempt_ledger import SourceAttemptLedger


def _source(task_id: str, url: str) -> CandidateSource:
    return CandidateSource(
        task_id=task_id,
        url=url,
        canonical_url=url,
        discovery_method="test",
        expected_content_kind=ContentKind.ANY,
    )


def _task(db, task_id: str) -> None:
    entity_id = f"station-{task_id}"
    db.execute(
        "INSERT INTO stations(entity_id, entity_type, canonical_name) VALUES (?, 'station', ?)",
        (entity_id, entity_id),
    )
    db.execute(
        """INSERT INTO tasks(
               task_id, entity_id, entity_type, task_type, target_period,
               status, created_at, updated_at
           ) VALUES (?, ?, 'station', 'station_generation', '2023',
                     'running', '2026-09-14T00:00:00Z', '2026-09-14T00:00:00Z')""",
        (task_id, entity_id),
    )
    db.commit()


def test_failed_source_does_not_prevent_next_independent_attempt(db):
    _task(db, "task-attempt-fallback")
    ledger = SourceAttemptLedger(db)
    first = ledger.start_attempt(_source("task-attempt-fallback", "https://bad.test/a"))
    ledger.fail(
        first,
        failure_stage="acquisition",
        failure_code="HTTP_404",
        error="not found",
    )
    second = ledger.start_attempt(_source("task-attempt-fallback", "https://good.test/b"))

    rows = db.execute(
        """SELECT status, failure_code FROM source_attempts
           WHERE task_id=? ORDER BY created_at, rowid""",
        ("task-attempt-fallback",),
    ).fetchall()
    assert [tuple(row) for row in rows] == [("failed", "HTTP_404"), ("running", None)]
    assert first.candidate_source_id != second.candidate_source_id
    source_rows = db.execute(
        """SELECT status FROM candidate_sources
           WHERE task_id=? ORDER BY created_at, rowid""",
        ("task-attempt-fallback",),
    ).fetchall()
    assert [row[0] for row in source_rows] == [
        CandidateSourceStatus.EXHAUSTED.value,
        CandidateSourceStatus.QUEUED.value,
    ]


def test_success_binds_attempt_to_archived_document_lineage(db):
    _task(db, "task-attempt-success")
    source = _source("task-attempt-success", "https://good.test/report")
    ledger = SourceAttemptLedger(db)
    attempt = ledger.start_attempt(source)
    db.execute(
        """INSERT INTO documents(
               document_id, task_id, original_url, file_size, content_hash,
               local_path, created_at
           ) VALUES ('doc-attempt', ?, ?, 7, ?, 'raw/doc', '2026-09-14T00:00:00Z')""",
        (source.task_id, source.url, "a" * 64),
    )
    db.commit()

    ledger.attach_document(attempt, document_id="doc-attempt", content_hash="a" * 64)
    assert db.execute(
        "SELECT status FROM source_attempts WHERE attempt_id=?", (attempt.attempt_id,)
    ).fetchone()[0] == "running"
    ledger.succeed(attempt, document_id="doc-attempt", content_hash="a" * 64)

    row = db.execute(
        "SELECT status, document_id FROM source_attempts WHERE attempt_id=?",
        (attempt.attempt_id,),
    ).fetchone()
    document = db.execute(
        "SELECT source_attempt_id, lineage_hash FROM documents WHERE document_id='doc-attempt'"
    ).fetchone()
    assert tuple(row) == ("succeeded", "doc-attempt")
    assert db.execute(
        "SELECT status FROM candidate_sources WHERE candidate_source_id=?",
        (source.candidate_source_id,),
    ).fetchone()[0] == CandidateSourceStatus.SUCCEEDED.value
    assert document[0] == attempt.attempt_id
    assert len(document[1]) == 64


def test_candidate_lineage_is_bound_to_the_source_attempt(db):
    _task(db, "task-candidate-lineage")
    source = _source("task-candidate-lineage", "https://good.test/report")
    ledger = SourceAttemptLedger(db)
    attempt = ledger.start_attempt(source)
    db.execute(
        """INSERT INTO documents(
               document_id, task_id, original_url, file_size, content_hash,
               local_path, created_at
           ) VALUES ('doc-candidate', ?, ?, 7, ?, 'raw/doc', '2026-09-14T00:00:00Z')""",
        (source.task_id, source.url, "a" * 64),
    )
    db.execute(
        """INSERT INTO extraction_candidates(
               candidate_id, task_id, entity_id, document_id, period_type,
               period_label, extracted_at
           ) VALUES ('cand-attempt', ?, ?, 'doc-candidate', 'calendar_year',
                     '2023', '2026-09-14T00:00:00Z')""",
        (source.task_id, "station-task-candidate-lineage"),
    )
    db.commit()

    lineage = ledger.bind_candidate(
        attempt,
        document_id="doc-candidate",
        candidate_id="cand-attempt",
        payload={"generation_gwh": 123.4, "metric": "gross_generation"},
        extractor_version="rules-v1",
    )

    row = db.execute(
        """SELECT source_attempt_id, lineage_hash FROM extraction_candidates
           WHERE candidate_id='cand-attempt'"""
    ).fetchone()
    assert tuple(row) == (attempt.attempt_id, lineage)
    assert len(lineage) == 64


def test_cancel_marks_attempt_and_candidate_cancelled(db):
    _task(db, "task-attempt-cancel")
    source = _source("task-attempt-cancel", "https://cancel.test/report")
    ledger = SourceAttemptLedger(db)
    attempt = ledger.start_attempt(source)

    ledger.cancel(attempt, reason="user cancelled")

    attempt_row = db.execute(
        "SELECT status, failure_code FROM source_attempts WHERE attempt_id=?",
        (attempt.attempt_id,),
    ).fetchone()
    source_status = db.execute(
        "SELECT status FROM candidate_sources WHERE candidate_source_id=?",
        (source.candidate_source_id,),
    ).fetchone()[0]
    assert tuple(attempt_row) == ("cancelled", "CANCELLED")
    assert source_status == CandidateSourceStatus.CANCELLED.value
