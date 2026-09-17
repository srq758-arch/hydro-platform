import sqlite3

from hydro_platform.app.queries import ReadQueries


def _connection(*, with_period_type: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE stations (
            entity_id TEXT PRIMARY KEY,
            canonical_name TEXT
        );
        CREATE TABLE projects (
            entity_id TEXT PRIMARY KEY,
            canonical_name TEXT
        );
        """
    )
    period_column = ", period_type TEXT" if with_period_type else ""
    conn.execute(
        f"""
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            task_type TEXT NOT NULL,
            target_period TEXT{period_column},
            status TEXT NOT NULL,
            priority_tier TEXT,
            failure_stage TEXT,
            last_error TEXT,
            source_type TEXT,
            user_specified_source TEXT,
            attempts INTEGER,
            max_attempts INTEGER,
            created_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO stations(entity_id, canonical_name) VALUES (?, ?)",
        ("station-1", "Example Station"),
    )
    columns = (
        "task_id, entity_id, entity_type, task_type, target_period, period_type, "
        "status, priority_tier, failure_stage, last_error, source_type, "
        "user_specified_source, attempts, max_attempts, created_at"
    )
    values = (
        "task-fiscal", "station-1", "station", "station_generation", "2024",
        "fiscal_year", "pending", "T1", None, None, "manual", "https://example.test",
        0, 3, "2026-09-17T00:00:00Z",
    )
    if with_period_type:
        conn.execute(f"INSERT INTO tasks ({columns}) VALUES ({','.join('?' for _ in values)})", values)
    else:
        legacy_values = values[:5] + values[6:]
        legacy_columns = columns.replace(", period_type", "")
        conn.execute(
            f"INSERT INTO tasks ({legacy_columns}) VALUES ({','.join('?' for _ in legacy_values)})",
            legacy_values,
        )
    conn.commit()
    return conn


def test_list_tasks_returns_period_type_for_current_schema():
    conn = _connection(with_period_type=True)
    try:
        result = ReadQueries(conn).list_tasks()
        assert result["items"][0]["period_type"] == "fiscal_year"
        assert result["items"][0]["source_type"] == "manual"
    finally:
        conn.close()


def test_list_tasks_defaults_legacy_schema_to_calendar_year():
    conn = _connection(with_period_type=False)
    try:
        result = ReadQueries(conn).list_tasks()
        assert result["items"][0]["period_type"] == "calendar_year"
    finally:
        conn.close()
