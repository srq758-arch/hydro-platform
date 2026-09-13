"""Pytest共享fixture配置。

提供测试数据库初始化、完整schema创建等通用fixture。
"""

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def test_db(tmp_path: Path):
    """创建临时测试数据库，包含完整schema和迁移。

    ⚠️ 步骤1.2修复：
    - 必须使用生产schema.sql
    - 必须应用生产迁移
    - 不允许维护单独的测试schema
    """
    db_path = tmp_path / "hydro_test.db"

    # 使用生产连接方式
    from hydro_platform.database.connection import connect
    conn = connect(db_path)

    # 执行生产schema
    schema_path = Path(__file__).parent.parent / "hydro_platform" / "database" / "schema.sql"
    if schema_path.exists():
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
            conn.executescript(schema_sql)
    else:
        # schema.sql不存在时报错，不使用fallback
        raise FileNotFoundError(f"生产schema不存在: {schema_path}")

    # 应用生产迁移（步骤1.2新增）
    from hydro_platform.database.migrations import migrate
    migrate(conn)

    conn.commit()

    yield conn

    # 清理
    conn.close()


@pytest.fixture
def db(test_db: sqlite3.Connection) -> sqlite3.Connection:
    """统一主数据库 fixture；保留 ``test_db`` 作为旧测试兼容别名。"""
    return test_db


@pytest.fixture
def test_db_with_foreign_keys_off(tmp_path: Path):
    """创建临时测试数据库，外键约束关闭（用于需要灵活清理数据的测试）。

    ⚠️ 步骤1.2修复：应用生产迁移
    """
    db_path = tmp_path / "hydro_no_foreign_keys.db"

    from hydro_platform.database.connection import connect
    conn = connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")  # 明确关闭外键

    schema_path = Path(__file__).parent.parent / "hydro_platform" / "database" / "schema.sql"
    if schema_path.exists():
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
            conn.executescript(schema_sql)
    else:
        raise FileNotFoundError(f"生产schema不存在: {schema_path}")

    # 应用生产迁移
    from hydro_platform.database.migrations import migrate
    migrate(conn)

    conn.commit()

    yield conn

    conn.close()


def _create_minimal_schema(conn: sqlite3.Connection):
    """创建最小化schema（当schema.sql不可用时）。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stations (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT DEFAULT 'station',
            canonical_name TEXT NOT NULL,
            aliases TEXT,
            local_name TEXT,
            country TEXT,
            country_2 TEXT,
            region TEXT,
            subregion TEXT,
            state_province TEXT,
            river TEXT,
            latitude REAL,
            longitude REAL,
            location_accuracy TEXT,
            capacity_mw REAL,
            turbines INTEGER,
            status TEXT,
            technology TEXT,
            operator TEXT,
            owner TEXT,
            commissioning_year INTEGER,
            retired_year INTEGER,
            gem_location_id TEXT,
            gem_unit_id TEXT,
            gem_wiki_url TEXT,
            priority_tier INTEGER DEFAULT 2,
            collection_priority INTEGER DEFAULT 50,
            needs_review INTEGER DEFAULT 0,
            source_seed TEXT,
            source_url TEXT,
            dataset_version TEXT,
            registry_version TEXT,
            raw_record_hash TEXT
        );

        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT,
            publisher TEXT,
            publish_date TEXT,
            retrieved_at TEXT,
            content_hash TEXT,
            archive_path TEXT,
            language TEXT,
            entity_id TEXT,
            entity_type TEXT DEFAULT 'station',
            source_url TEXT,
            canonical_url TEXT,
            source_type TEXT,
            document_type TEXT,
            covered_metric TEXT,
            covered_year INTEGER,
            access_method TEXT DEFAULT 'http',
            source_reliability_score REAL DEFAULT 0.5,
            task_fit_score REAL,
            record_confidence_score REAL,
            match_reason TEXT,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            last_success TEXT,
            last_failure TEXT,
            failure_reason TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            fact_type TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            snippet TEXT,
            page_number INTEGER,
            table_reference TEXT,
            confidence REAL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE IF NOT EXISTS generation_records (
            record_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            entity_type TEXT DEFAULT 'station',
            period_label TEXT NOT NULL,
            period_type TEXT DEFAULT 'calendar_year',
            generation_gwh REAL NOT NULL,
            capacity_factor REAL,
            value_type TEXT DEFAULT 'actual',
            measurement_scope TEXT DEFAULT 'plant',
            publication_status TEXT DEFAULT 'draft',
            review_status TEXT DEFAULT 'open',
            validation_status TEXT,
            evidence_id TEXT,
            confidence REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (entity_id) REFERENCES stations(entity_id),
            FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            task_type TEXT NOT NULL,
            target_period TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            priority_tier TEXT,
            collection_priority INTEGER,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3,
            failure_stage TEXT,
            last_error TEXT,
            source_type TEXT DEFAULT 'automatic',
            user_specified_source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS review_items (
            review_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            fact_type TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            payload TEXT,
            resolved_value TEXT,
            reviewer TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            task_id TEXT,
            candidate_id TEXT
        );

        CREATE TABLE IF NOT EXISTS extraction_candidates (
            candidate_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            fact_type TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            generation_gwh REAL,
            period_label TEXT,
            value_type TEXT DEFAULT 'actual',
            confidence REAL,
            review_status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY (entity_id) REFERENCES stations(entity_id),
            FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
        );

        CREATE INDEX IF NOT EXISTS idx_generation_records_entity ON generation_records(entity_id);
        CREATE INDEX IF NOT EXISTS idx_generation_records_period ON generation_records(period_label);
        CREATE INDEX IF NOT EXISTS idx_generation_records_status ON generation_records(publication_status, review_status);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_review_items_status ON review_items(status);
    """)
