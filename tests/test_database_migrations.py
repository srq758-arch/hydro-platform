"""测试数据库迁移机制。

验证：
1. 干净环境启动可自动创建所有表
2. 已有数据库升级时不破坏数据
3. 迁移历史可查询
4. 幂等性（重复执行不报错）
"""

import sqlite3
import tempfile
from pathlib import Path

from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import migrate, _applied_version, CURRENT_VERSION
# ❌ 已删除：get_migration_status函数不存在（步骤1.1修复）
# 改用 _applied_version


def test_fresh_database():
    """测试1：干净环境创建数据库"""
    print("\n=== 测试1：干净环境创建数据库 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(db_path)

        # 执行迁移
        version = migrate(conn)
        print(f"✓ 迁移完成，当前版本: v{version}")

        # 验证版本
        assert version == CURRENT_VERSION, f"版本不匹配: {version} != {CURRENT_VERSION}"

        # 验证核心表已创建
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        print(f"✓ 已创建 {len(tables)} 个表:")
        for table in tables:
            print(f"  - {table}")

        # 验证必要的表存在
        required_tables = [
            'schema_version', 'stations', 'projects', 'tasks', 'sources',
            'generation_records', 'evidence', 'review_items', 'documents',
            'task_runs', 'project_station_links', 'project_status_history'
        ]

        for table in required_tables:
            assert table in tables, f"缺少表: {table}"

        print(f"✓ 所有必需表已创建")

        # 验证迁移历史
        cursor = conn.execute("SELECT version, applied_at FROM schema_version ORDER BY version")
        migrations = cursor.fetchall()
        print(f"\n✓ 迁移历史:")
        for ver, applied_at in migrations:
            print(f"  v{ver}: {applied_at}")

        conn.close()
        print("\n✓ 测试1通过")


def test_migration_idempotency():
    """测试2：迁移幂等性（重复执行不报错）"""
    print("\n=== 测试2：迁移幂等性 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(db_path)

        # 第一次迁移
        v1 = migrate(conn)
        print(f"✓ 第一次迁移: v{v1}")

        # 第二次迁移（应该跳过）
        v2 = migrate(conn)
        print(f"✓ 第二次迁移: v{v2} (跳过)")

        assert v1 == v2, "重复迁移改变了版本号"

        # 验证没有重复记录
        cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
        count = cursor.fetchone()[0]
        print(f"✓ 迁移记录数: {count}")

        # 应该有 CURRENT_VERSION 条记录（每个版本一条）
        assert count == CURRENT_VERSION, f"迁移记录数不对: {count} != {CURRENT_VERSION}"

        conn.close()
        print("\n✓ 测试2通过")


def test_migration_status():
    """测试3：迁移状态查询"""
    print("\n=== 测试3：迁移状态查询 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(db_path)

        # 执行迁移
        migrate(conn)

        # 查询当前版本（使用_applied_version）
        current_version = _applied_version(conn)
        print(f"✓ 迁移状态:")
        print(f"  当前版本: v{current_version}")
        print(f"  最新版本: v{CURRENT_VERSION}")

        is_up_to_date = (current_version == CURRENT_VERSION)
        print(f"  是否最新: {is_up_to_date}")

        assert is_up_to_date, "数据库未更新到最新版本"
        assert current_version == CURRENT_VERSION

        conn.close()
        print("\n✓ 测试3通过")


def test_data_preservation():
    """测试4：升级时数据不丢失"""
    print("\n=== 测试4：数据保留测试 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(db_path)

        # 第一次迁移
        migrate(conn)

        # 插入测试数据
        test_entity_id = "TEST_station_001"
        conn.execute("""
            INSERT INTO stations (entity_id, entity_type, canonical_name)
            VALUES (?, 'station', 'Test Station')
        """, (test_entity_id,))
        conn.commit()
        print(f"✓ 插入测试数据: {test_entity_id}")

        # 验证数据存在
        row = conn.execute(
            "SELECT canonical_name FROM stations WHERE entity_id = ?",
            (test_entity_id,)
        ).fetchone()
        assert row is not None, "测试数据插入失败"
        print(f"✓ 数据验证: {row[0]}")

        # 重新迁移（模拟升级）
        migrate(conn)

        # 验证数据仍然存在
        row = conn.execute(
            "SELECT canonical_name FROM stations WHERE entity_id = ?",
            (test_entity_id,)
        ).fetchone()
        assert row is not None, "升级后数据丢失"
        print(f"✓ 升级后数据仍存在: {row[0]}")

        conn.close()
        print("\n✓ 测试4通过")


def test_new_tables():
    """测试5：验证新增表已创建"""
    print("\n=== 测试5：验证新增表 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(db_path)

        try:
            migrate(conn)

            # 先插入必需的项目和电站数据（满足外键约束）
            conn.execute("""
                INSERT INTO projects (entity_id, entity_type, canonical_name)
                VALUES ('proj_001', 'project', 'Test Project')
            """)
            conn.execute("""
                INSERT INTO stations (entity_id, entity_type, canonical_name)
                VALUES ('sta_001', 'station', 'Test Station')
            """)
            conn.commit()

            # 验证 project_station_links 表
            conn.execute("""
                INSERT INTO project_station_links
                (project_id, station_id, link_type, created_at)
                VALUES ('proj_001', 'sta_001', 'commissioning', '2026-09-08T00:00:00')
            """)
            conn.commit()
            print("✓ project_station_links 表可用")

            # 验证 project_status_history 表
            conn.execute("""
                INSERT INTO project_status_history
                (project_id, status, recorded_at)
                VALUES ('proj_001', 'under_construction', '2026-09-08T00:00:00')
            """)
            conn.commit()
            print("✓ project_status_history 表可用")

            # 验证视图
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='view' AND name LIKE 'v_%'
            """)
            views = [row[0] for row in cursor.fetchall()]
            print(f"✓ 已创建 {len(views)} 个视图:")
            for view in views:
                print(f"  - {view}")

            expected_views = ['v_top100_generation', 'v_review_queue_stats', 'v_task_stats']
            for view in expected_views:
                assert view in views, f"缺少视图: {view}"

            print("\n✓ 测试5通过")

        finally:
            conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("数据库迁移机制测试")
    print("=" * 60)

    try:
        test_fresh_database()
        test_migration_idempotency()
        test_migration_status()
        test_data_preservation()
        test_new_tables()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
