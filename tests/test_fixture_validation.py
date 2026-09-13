"""验证fixture与生产初始化一致（步骤1.2）"""
import pytest


def test_fixture_has_all_required_tables(test_db):
    """验证fixture创建了所有必需的表"""
    conn = test_db
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]

    # 核心必需表
    required = [
        'stations', 'generation_records', 'tasks', 'sources', 'documents',
        'evidence', 'review_items', 'schema_version'
    ]

    missing = [t for t in required if t not in tables]
    assert len(missing) == 0, f"缺少必需的表: {missing}"

    print(f"[OK] All {len(required)} required tables exist")
    print(f"  Total tables: {len(tables)}")


def test_fixture_foreign_keys_enabled(test_db):
    """验证外键约束已启用"""
    conn = test_db
    cursor = conn.execute("PRAGMA foreign_keys")
    fk_enabled = cursor.fetchone()[0]
    assert fk_enabled == 1, "外键约束未启用"
    print("[OK] Foreign keys enabled")


def test_fixture_schema_version_matches_production(test_db):
    """验证迁移版本与生产一致"""
    conn = test_db
    from hydro_platform.database.migrations import _applied_version, CURRENT_VERSION

    version = _applied_version(conn)
    assert version == CURRENT_VERSION, \
        f"迁移版本不一致: fixture v{version}, production v{CURRENT_VERSION}"

    print(f"[OK] Migration version matches production: v{version}")


def test_fixture_uses_temp_directory(test_db):
    """验证fixture使用临时目录，不污染生产"""
    conn = test_db
    cursor = conn.execute("PRAGMA database_list")
    db_path = cursor.fetchone()[2]

    # 临时文件通常包含tmp或temp
    is_temp = 'tmp' in db_path.lower() or 'temp' in db_path.lower()
    assert is_temp, f"数据库应在临时目录: {db_path}"

    print(f"[OK] Using temp database: {db_path}")


def test_fixture_no_production_pollution(test_db):
    """验证fixture不污染生产数据库"""
    conn = test_db

    # 临时数据库不应该在项目目录内
    cursor = conn.execute("PRAGMA database_list")
    db_path = cursor.fetchone()[2]

    # 不应包含项目路径
    assert 'hydro_platform_v1' not in db_path, \
        f"测试数据库不应在项目目录: {db_path}"

    print("[OK] No production pollution")
