"""PyInstaller 资源契约：安装包不得携带用户运行数据。"""

from pathlib import Path


def test_spec_packages_resources_without_runtime_database():
    project = Path(__file__).parents[2]
    spec = (project / "hydro_platform.spec").read_text(encoding="utf-8")

    assert "('data', 'data')" not in spec
    assert "('data/seed', 'data/seed')" in spec
    assert "('hydro_platform/app/web', 'hydro_platform/app/web')" in spec
    assert "('hydro_platform/database/schema.sql', 'hydro_platform/database')" in spec
    assert "('hydro_platform/database/migrations', 'hydro_platform/database/migrations')" in spec
    assert "'pypdf'," not in spec
    assert "'pdfplumber'," not in spec
    assert "'openpyxl'," not in spec
    assert (project / "data" / "seed").is_dir()
    assert (project / "hydro_platform" / "database" / "schema.sql").is_file()
    assert (project / "hydro_platform" / "database" / "migrations").is_dir()
