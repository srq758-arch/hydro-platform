"""V6 数据库结构契约回归测试。

这些测试不依赖业务库；所有数据库均位于 pytest 的临时目录。
"""

from __future__ import annotations

import pytest

from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import (
    CURRENT_VERSION,
    _applied_version,
    migrate,
    verify_schema_contract_v6,
)


def test_v5_database_is_repaired_to_v6(tmp_path):
    """已记录为 v5 但缺少两列的数据库必须升级为完整 v6。"""
    conn = connect(tmp_path / "legacy-v5.db")
    try:
        assert migrate(conn, target_version=5) == 5
        assert not any(
            row[1] == "candidate_id"
            for row in conn.execute("PRAGMA table_info(review_items)")
        )
        assert not any(
            row[1] == "review_status"
            for row in conn.execute("PRAGMA table_info(extraction_candidates)")
        )

        assert migrate(conn) == CURRENT_VERSION
        valid, message = verify_schema_contract_v6(conn)
        assert valid, message
        assert _applied_version(conn) == CURRENT_VERSION
    finally:
        conn.close()


def test_v6_does_not_mark_database_current_after_repair_failure(tmp_path):
    """v6 任一前置表缺失时，必须失败且不得登记新版本。"""
    conn = connect(tmp_path / "broken-v5.db")
    try:
        assert migrate(conn, target_version=5) == 5
        conn.execute("DROP TABLE review_events")
        conn.commit()

        with pytest.raises(RuntimeError, match="缺少基础表"):
            migrate(conn)

        assert _applied_version(conn) == 5
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_events'"
        ).fetchone() is None
    finally:
        conn.close()
