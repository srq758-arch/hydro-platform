"""v13 必须真实迁移旧库，且不能猜测历史 lineage。"""

import sqlite3

import pytest

from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import (
    _applied_version,
    migrate,
    verify_source_pipeline_contract_v13,
    verify_task_lease_contract_v14,
)


def test_v12_to_v13_preserves_legacy_rows_without_guessing_lineage(tmp_path):
    conn = connect(tmp_path / "legacy-v12.db")
    migrate(conn, target_version=12)
    conn.execute(
        "INSERT INTO stations(entity_id, entity_type, canonical_name) VALUES (?, ?, ?)",
        ("station-1", "station", "Station One"),
    )
    conn.execute(
        """INSERT INTO tasks(
               task_id, entity_id, entity_type, task_type, target_period,
               status, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "task-1", "station-1", "station", "station_generation", "2023",
            "pending", "2026-09-14T00:00:00Z", "2026-09-14T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO sources(source_id, url) VALUES (?, ?)",
        ("source-1", "https://example.test/report"),
    )
    conn.execute(
        """INSERT INTO documents(
               document_id, task_id, source_id, original_url, file_size,
               content_hash, local_path, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "doc-legacy", "task-1", "source-1", "https://example.test/report",
            1, "a" * 64, "raw/legacy.html", "2026-09-14T00:00:00Z",
        ),
    )
    conn.execute(
        """INSERT INTO extraction_candidates(
               candidate_id, task_id, entity_id, document_id, period_type,
               period_label, extracted_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "cand-legacy", "task-1", "station-1", "doc-legacy",
            "calendar_year", "2023", "2026-09-14T00:00:00Z",
        ),
    )
    conn.commit()

    assert migrate(conn, target_version=13) == 13
    assert _applied_version(conn) == 13
    ok, message = verify_source_pipeline_contract_v13(conn)
    assert ok, message

    document = conn.execute(
        "SELECT source_attempt_id, lineage_hash FROM documents WHERE document_id='doc-legacy'"
    ).fetchone()
    candidate = conn.execute(
        """SELECT source_attempt_id, lineage_hash
           FROM extraction_candidates WHERE candidate_id='cand-legacy'"""
    ).fetchone()
    assert tuple(document) == (None, None)
    assert tuple(candidate) == (None, None)

    # Re-running v13 validates the contract and does not duplicate/alter old data.
    assert migrate(conn, target_version=13) == 13
    assert conn.execute("SELECT COUNT(*) FROM search_leads").fetchone()[0] == 0
    conn.close()


def test_v13_enforces_attempt_parent_and_attempt_number_uniqueness(test_db):
    test_db.execute(
        "INSERT INTO stations(entity_id, entity_type, canonical_name) VALUES (?, ?, ?)",
        ("station-lineage", "station", "Lineage Station"),
    )
    test_db.execute(
        """INSERT INTO tasks(
               task_id, entity_id, entity_type, task_type, target_period,
               status, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "task-lineage", "station-lineage", "station", "station_generation", "2023",
            "pending", "2026-09-14T00:00:00Z", "2026-09-14T00:00:00Z",
        ),
    )
    test_db.execute(
        """INSERT INTO candidate_sources(
               candidate_source_id, task_id, url, canonical_url,
               discovery_method, status, lineage_hash, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "src-lineage", "task-lineage", "https://example.test/a",
            "https://example.test/a", "manual", "eligible", "b" * 64,
            "2026-09-14T00:00:00Z",
        ),
    )
    test_db.execute(
        """INSERT INTO source_attempts(
               attempt_id, task_id, candidate_source_id, attempt_no, status, created_at
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "attempt-1", "task-lineage", "src-lineage", 1, "pending",
            "2026-09-14T00:00:00Z",
        ),
    )
    with pytest.raises(sqlite3.IntegrityError):
        test_db.execute(
            """INSERT INTO source_attempts(
                   attempt_id, task_id, candidate_source_id, attempt_no, status, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "attempt-duplicate", "task-lineage", "src-lineage", 1, "pending",
                "2026-09-14T00:00:00Z",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        test_db.execute(
            """INSERT INTO source_attempts(
                   attempt_id, task_id, candidate_source_id, attempt_no, status, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "attempt-orphan", "task-lineage", "missing-source", 2, "pending",
                "2026-09-14T00:00:00Z",
            ),
        )


def test_v13_to_v14_adds_empty_lease_metadata_without_rewriting_tasks(tmp_path):
    conn = connect(tmp_path / "legacy-v13.db")
    migrate(conn, target_version=13)
    conn.execute(
        "INSERT INTO stations(entity_id, entity_type, canonical_name) VALUES ('station-lease', 'station', 'Lease')"
    )
    conn.execute(
        """INSERT INTO tasks(
               task_id, entity_id, entity_type, task_type, target_period,
               status, attempts, created_at, updated_at
           ) VALUES ('task-lease', 'station-lease', 'station', 'station_generation',
                     '2023', 'failed', 2, '2026-09-14T00:00:00Z', '2026-09-14T00:00:00Z')"""
    )
    conn.commit()

    assert migrate(conn, target_version=14) == 14
    ok, message = verify_task_lease_contract_v14(conn)
    assert ok, message
    row = conn.execute(
        """SELECT status, attempts, worker_id, lease_expires_at, heartbeat_at
           FROM tasks WHERE task_id='task-lease'"""
    ).fetchone()
    assert tuple(row) == ("failed", 2, None, None, None)
    conn.close()
