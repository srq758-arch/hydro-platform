"""启动前数据库检查只允许为空用户空间首次建库。"""

import sqlite3

import pytest

import hydro_platform.app.gui.main_window as main_window
from hydro_platform.app.gui.main_window import _production_database_needs_bootstrap
from hydro_platform.config.paths import get_database_path
from hydro_platform.database.migrations import CURRENT_VERSION


def test_missing_or_empty_database_requires_bootstrap(tmp_path):
    missing = tmp_path / "missing.db"
    assert _production_database_needs_bootstrap(missing) is True

    empty = tmp_path / "empty.db"
    empty.touch()
    assert _production_database_needs_bootstrap(empty) is True


def test_existing_schema_database_does_not_bootstrap(tmp_path):
    db_path = tmp_path / "existing.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.commit()
    conn.close()

    assert _production_database_needs_bootstrap(db_path) is False


def test_corrupt_existing_database_is_blocked(tmp_path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"not a sqlite database")

    with pytest.raises(RuntimeError, match="生产数据库不可读"):
        _production_database_needs_bootstrap(db_path)


def test_create_window_bootstraps_before_scheduler_and_webview(monkeypatch, tmp_path):
    events = []
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path))

    class FakeScheduler:
        def __init__(self, **kwargs):
            events.append("scheduler_construct")

        def start(self):
            events.append("scheduler_start")

    monkeypatch.setattr(main_window, "TaskScheduler", FakeScheduler)
    monkeypatch.setattr(
        main_window.webview,
        "create_window",
        lambda *args, **kwargs: events.append("webview_create") or object(),
    )
    monkeypatch.setattr(
        main_window.webview,
        "start",
        lambda *args, **kwargs: events.append("webview_start"),
    )

    main_window.create_window()

    db_path = get_database_path("production")
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT max(version) FROM schema_version").fetchone()[0] == CURRENT_VERSION
    finally:
        conn.close()

    assert events == [
        "scheduler_construct",
        "scheduler_start",
        "webview_create",
        "webview_start",
    ]
