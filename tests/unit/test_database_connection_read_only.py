"""Windows/跨盘路径的只读连接必须能打开既有数据库，且不可写。"""

import sqlite3

import pytest

from hydro_platform.database.connection import connect


def test_read_only_connection_uses_valid_file_uri(tmp_path):
    db_path = tmp_path / "readonly.db"
    writable = sqlite3.connect(db_path)
    writable.execute("CREATE TABLE marker (value TEXT)")
    writable.execute("INSERT INTO marker VALUES ('ok')")
    writable.commit()
    writable.close()

    readonly = connect(db_path, read_only=True)
    assert readonly.execute("SELECT value FROM marker").fetchone()[0] == "ok"
    with pytest.raises(sqlite3.OperationalError):
        readonly.execute("INSERT INTO marker VALUES ('blocked')")
    readonly.close()


def test_read_only_connection_falls_back_to_immutable_snapshot_without_sidecars(tmp_path, monkeypatch):
    """跨盘 Windows 文件系统无法建立只读锁时，稳定库仍可安全查询。"""
    db_path = tmp_path / "immutable-fallback.db"
    writable = sqlite3.connect(db_path)
    writable.execute("CREATE TABLE marker (value TEXT)")
    writable.execute("INSERT INTO marker VALUES ('ok')")
    writable.commit()
    writable.close()

    original_connect = sqlite3.connect
    calls = []

    def fail_standard_then_open(database, *args, **kwargs):
        calls.append(database)
        if kwargs.get("uri") and "immutable=1" not in str(database):
            raise sqlite3.OperationalError("unable to open database file")
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", fail_standard_then_open)
    readonly = connect(db_path, read_only=True)
    try:
        assert readonly.execute("SELECT value FROM marker").fetchone()[0] == "ok"
        assert any("mode=ro" in str(uri) for uri in calls)
        assert any("immutable=1" in str(uri) for uri in calls)
    finally:
        readonly.close()
