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
