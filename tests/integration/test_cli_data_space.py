"""CLI 入口必须使用统一连接工厂并显示实际数据空间。"""

from pathlib import Path

from click.testing import CliRunner

from hydro_platform.app.cli import cli
from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import migrate


def test_cli_status_uses_explicit_isolated_database(tmp_path):
    db_path = tmp_path / "cli.db"
    conn = connect(db_path)
    schema = Path(__file__).parents[2] / "hydro_platform" / "database" / "schema.sql"
    conn.executescript(schema.read_text(encoding="utf-8"))
    migrate(conn)
    conn.close()

    result = CliRunner().invoke(cli, ["status", "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert str(db_path) in result.output
