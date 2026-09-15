"""测试 D01/D10/D17 修复：入口点与打包

D01: 用户指定来源不被自动搜索替换
D10: 任务重试不丢失用户来源
D17: pyinstaller打包资源完整性
"""

import sqlite3
import pytest
from pathlib import Path

from hydro_platform.models.task import Task
from hydro_platform.common.enums import TaskType, TaskStatus
from hydro_platform.database.repositories import TaskRepository
from hydro_platform.pipeline.source_resolver import resolve_sources_enhanced
from hydro_platform.pipeline.context import PipelineContext


class TestD01_UserSpecifiedSource:
    """D01: 用户手动指定的来源不被自动搜索替换"""

    def test_manual_source_bypasses_discovery(self, tmp_path):
        """用户手动指定的URL不应触发Discovery自动搜索"""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # 创建tasks表（完整schema）
        conn.execute("""
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                entity_id TEXT,
                entity_type TEXT,
                task_type TEXT,
                target_period TEXT,
                status TEXT,
                priority_tier TEXT,
                collection_priority INTEGER,
                source_type TEXT DEFAULT 'automatic',
                user_specified_source TEXT,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                failure_stage TEXT,
                last_error TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # 创建手动指定来源的任务
        manual_task = Task(
            task_id="US001::generation::2024",
            entity_id="US001",
            entity_type="station",
            task_type=TaskType.STATION_GENERATION,
            target_period="2024",
            source_type="manual",
            user_specified_source="https://example.com/manual-report.pdf"
        )

        repo = TaskRepository(conn)
        repo.upsert_many([manual_task])

        # 从数据库读取任务
        row = conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (manual_task.task_id,)
        ).fetchone()

        # 构造任务对象（模拟orchestrator读取）
        task_obj = type('Task', (), {
            'entity_id': row['entity_id'],
            'target_period': row['target_period'],
            'source_type': row['source_type'],
            'user_specified_source': row['user_specified_source']
        })()

        # 调用resolve_sources_enhanced
        sources = resolve_sources_enhanced(conn, task_obj)

        # 验证：应该直接返回用户指定的来源
        assert len(sources) == 1
        assert sources[0].url == "https://example.com/manual-report.pdf"
        assert sources[0].title == "用户指定来源"

        conn.close()

    def test_automatic_source_triggers_discovery(self, tmp_path):
        """自动模式应该允许Discovery搜索"""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        conn.execute("""
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                entity_id TEXT,
                entity_type TEXT,
                task_type TEXT,
                target_period TEXT,
                status TEXT,
                priority_tier TEXT,
                collection_priority INTEGER,
                source_type TEXT DEFAULT 'automatic',
                user_specified_source TEXT,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                failure_stage TEXT,
                last_error TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # 创建stations表（供_get_entity_name查询）
        conn.execute("""
            CREATE TABLE stations (
                entity_id TEXT PRIMARY KEY,
                canonical_name TEXT,
                country TEXT
            )
        """)
        conn.execute(
            "INSERT INTO stations (entity_id, canonical_name, country) VALUES (?, ?, ?)",
            ("US002", "Test Station", "US")
        )

        # 创建自动任务（无用户指定来源）
        auto_task = Task(
            task_id="US002::generation::2024",
            entity_id="US002",
            entity_type="station",
            task_type=TaskType.STATION_GENERATION,
            target_period="2024",
            source_type="automatic",
            user_specified_source=None
        )

        repo = TaskRepository(conn)
        repo.upsert_many([auto_task])

        row = conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (auto_task.task_id,)
        ).fetchone()

        task_obj = type('Task', (), {
            'entity_id': row['entity_id'],
            'target_period': row['target_period'],
            'source_type': row['source_type'],
            'user_specified_source': row['user_specified_source']
        })()

        # 不应该返回手动来源（会进入Discovery或fallback）
        sources = resolve_sources_enhanced(conn, task_obj)

        # 如果没有Discovery结果，sources可能为空或来自fallback
        # 关键是：不应该有"用户手动指定"标记
        if sources:
            assert sources[0].title != "用户指定来源"

        conn.close()


class TestD10_RetryPreservesSource:
    """D10: 任务重试时保留用户指定来源"""

    def test_retry_preserves_user_source(self, tmp_path):
        """重试失败任务时，user_specified_source字段应该保留"""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        conn.execute("""
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                entity_id TEXT,
                entity_type TEXT,
                task_type TEXT,
                target_period TEXT,
                status TEXT,
                source_type TEXT DEFAULT 'automatic',
                user_specified_source TEXT,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                failure_stage TEXT,
                last_error TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        from hydro_platform.common.clock import now_iso
        now = now_iso()

        # 插入一个失败的手动任务
        conn.execute("""
            INSERT INTO tasks (
                task_id, entity_id, entity_type, task_type, target_period,
                status, source_type, user_specified_source, attempts, max_attempts,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "US003::generation::2024",
            "US003",
            "station",
            "generation",
            "2024",
            "failed",
            "manual",
            "https://example.com/user-report.pdf",
            1,
            3,
            now,
            now
        ))
        conn.commit()

        # 重试任务（模拟TaskManager.requeue）
        from hydro_platform.tasking.manager import TaskManager
        tm = TaskManager(conn)

        success = tm.requeue("US003::generation::2024")
        assert success, "重试应该成功"

        # 验证：user_specified_source应该保留
        row = conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            ("US003::generation::2024",)
        ).fetchone()

        assert row['status'] == 'pending'
        assert row['source_type'] == 'manual'
        assert row['user_specified_source'] == 'https://example.com/user-report.pdf'

        conn.close()


class TestD17_PackagingResources:
    """D17: pyinstaller打包资源完整性"""

    def test_spec_includes_web_resources(self):
        """验证.spec文件包含web资源"""
        spec_path = Path("F:/hydro_platform_v1/hydro_platform.spec")
        assert spec_path.exists(), "spec文件应该存在"

        spec_content = spec_path.read_text(encoding='utf-8')

        # 验证关键资源被包含
        assert "hydro_platform/app/web" in spec_content, "应该打包web目录"
        assert "hydro_platform/database/schema.sql" in spec_content, "应该打包schema.sql"
        assert "hydro_platform/database/migrations" in spec_content, "应该打包migrations目录"

    def test_web_resources_exist(self):
        """验证web资源文件存在"""
        web_dir = Path("F:/hydro_platform_v1/hydro_platform/app/web")
        assert web_dir.exists(), "web目录应该存在"

        # 验证关键文件
        assert (web_dir / "index.html").exists(), "index.html应该存在"
        assert (web_dir / "app.js").exists(), "app.js应该存在"
        assert (web_dir / "styles.css").exists(), "styles.css应该存在"

    def test_migration_scripts_exist(self):
        """验证迁移脚本存在"""
        migrations_dir = Path("F:/hydro_platform_v1/hydro_platform/database/migrations")
        assert migrations_dir.exists(), "migrations目录应该存在"

        # 验证D01/D10的迁移脚本已创建
        migration_004 = migrations_dir / "004_add_source_tracking.sql"
        assert migration_004.exists(), "004迁移脚本应该存在"

        content = migration_004.read_text(encoding='utf-8')
        assert "source_type" in content
        assert "user_specified_source" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
