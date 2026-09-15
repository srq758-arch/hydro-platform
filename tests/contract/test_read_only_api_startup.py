"""GUI 启动与 SQLite 查询连接契约。

生产库可能仍停留在历史 v5 且含待治理的外键孤儿。只读页面不能因为每次
查询都重复执行迁移而失败或把瞬时写锁放大；迁移仍由显式 initialize() 入口
负责。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hydro_platform.app.api import Api
from hydro_platform.database import connection as connection_module


def test_read_dashboard_does_not_run_migration(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("production")
    api.initialize()

    def fail_migration(*args, **kwargs):
        raise AssertionError("查询路径不应触发 schema migration")

    monkeypatch.setattr("hydro_platform.app.api.migrate", fail_migration)
    dashboard = api.get_dashboard()

    assert dashboard["asset_cards"]["stations"] == 0
    assert dashboard["asset_cards"]["projects"] == 0


def test_connect_exposes_busy_timeout_and_read_only_mode(tmp_path: Path):
    db_path = tmp_path / "hydro.db"
    writable = connection_module.connect(db_path)
    writable.execute("CREATE TABLE probe(value TEXT)")
    writable.commit()
    writable.close()

    readonly = connection_module.connect(db_path, read_only=True)
    try:
        assert readonly.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
        assert readonly.execute("SELECT COUNT(*) FROM probe").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute("CREATE TABLE should_fail(value TEXT)")
    finally:
        readonly.close()


def test_frontend_navigation_preserves_session_state_contract():
    app_js = (Path(__file__).parents[2] / "hydro_platform" / "app" / "web" / "app.js").read_text(
        encoding="utf-8"
    )

    # Navigation must preserve the object that carries the boot guard and the
    # per-page draft state.  Do not bind this contract to the old, exact
    # ``params`` assignment: navigation now intentionally sanitises transient
    # route flags into ``visibleParams`` before exposing them to renderers.
    assert "if (appState._booted) return;" in app_js
    assert "pageStates: Object.create(null)" in app_js
    assert "snapshotCurrentPageState();" in app_js
    assert "appState = { ...appState, route, params: visibleParams };" in app_js


def test_data_space_info_reports_legacy_database_without_migrating(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("production")
    api.initialize()

    def fail_migration(*args, **kwargs):
        raise AssertionError("状态页不应隐式执行 schema migration")

    monkeypatch.setattr("hydro_platform.app.api.migrate", fail_migration)
    info = api.get_data_space_info()

    from hydro_platform.database.migrations import CURRENT_VERSION
    assert info["schema_version"] == CURRENT_VERSION
    assert info["foreign_key_violations"] == 0
    assert info["migration_required"] is False
