from __future__ import annotations

import sqlite3

from hydro_platform.database.migrations import CURRENT_VERSION, SCHEMA_FILE, migrate


def _legacy_schema_sql() -> str:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    return sql.replace(
        "UNIQUE (entity_id, task_type, target_period, period_type)",
        "UNIQUE (entity_id, task_type, target_period)",
        1,
    )


def _task_values(task_id: str, period_type: str = "calendar_year") -> tuple[str, ...]:
    return (
        task_id, "station-1", "station", "station_generation", "2022", period_type,
        "pending", "standard", None, 0, 3, None, None, "automatic", None,
        "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", None, None, None,
    )


def test_v17_rebuilds_legacy_task_unique_key_and_preserves_children():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_legacy_schema_sql())
    assert migrate(conn, target_version=16) == 16

    columns = [row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({placeholders})",
        _task_values("calendar-task"),
    )
    conn.execute(
        "INSERT INTO task_runs(task_id, attempt, status, started_at) "
        "VALUES (?, 1, 'started', '2026-01-01T00:00:00Z')",
        ("calendar-task",),
    )
    conn.commit()

    assert migrate(conn) == CURRENT_VERSION
    conn.execute(
        f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({placeholders})",
        _task_values("fiscal-task", "fiscal_year"),
    )
    conn.commit()

    rows = conn.execute(
        "SELECT task_id, period_type FROM tasks ORDER BY task_id"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        ("calendar-task", "calendar_year"),
        ("fiscal-task", "fiscal_year"),
    ]
    assert conn.execute("SELECT task_id FROM task_runs").fetchone()[0] == "calendar-task"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    conn.close()
