import sqlite3

from hydro_platform.app.api import Api


def test_production_and_test_api_use_different_database_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    production = Api("production")
    testing = Api("test")

    assert production.db_path != testing.db_path
    assert production.db_path.name == "hydro.db"
    assert testing.db_path.name == "hydro_test.db"
    assert production.raw_root != testing.raw_root

    production.initialize()
    testing.initialize()
    with sqlite3.connect(production.db_path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stations'").fetchone()
    with sqlite3.connect(testing.db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS isolation_probe(value TEXT)")
        conn.execute("INSERT INTO isolation_probe VALUES ('test-only')")
        conn.commit()

    with sqlite3.connect(production.db_path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='isolation_probe'").fetchone() is None


def test_reset_test_data_is_forbidden_on_production(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("production")
    try:
        api.reset_test_data()
    except PermissionError:
        pass
    else:
        raise AssertionError("production API must not reset test data")
