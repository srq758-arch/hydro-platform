"""数据库迁移执行器（v5增强版）。

支持版本化迁移：每个迁移对应一个版本号和 SQL 文件。
runner 幂等：已执行的迁移不会重复执行；但即使版本号已经存在，
最新的结构契约仍会被验证，避免出现“版本已登记、结构不完整”。

D15修复：
- 迁移失败时不会被误标记为成功
- 逐项验证关键列是否存在
- 提供详细的失败诊断信息

迁移列表：
- v1: 初始 schema（schema.sql）
- v2: 扩展 sources 表（001_extend_sources_table.sql）
- v3: 项目-电站关联表（002_add_project_station_links.sql）
- v4: Products 输出层视图（003_add_products_views.sql）
- v5: 候选/事实分离、外键修复（005_candidate_separation.sql）
- v6: 结构契约纠偏（006_schema_contract_repair.sql）
- v7: 候选可空字段契约纠偏（007_candidate_nullable_contract.sql）
- v8: 收紧可信出口视图（008_trustworthy_views.sql）
- v9: 来源发现候选台账（009_source_discovery_ledger.sql）
- v10: 来源候选 URL 访问探测（010_source_discovery_probe.sql）
- v11: DeepSeek 自然语言任务规划台账（011_intelligent_task_plans.sql）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from ..common.clock import now_iso
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
MIGRATIONS_DIR = Path(__file__).with_name("migrations")

# 迁移定义：(版本号, SQL 文件名, 描述, 验证函数)
MIGRATIONS = [
    (1, None, "初始 schema", None),  # None 表示使用 schema.sql
    (2, "001_extend_sources_table.sql", "扩展 sources 表", "verify_sources_v2"),
    (3, "002_add_project_station_links.sql", "添加项目-电站关联表", "verify_links_v3"),
    (4, "003_add_products_views.sql", "添加 Products 输出层视图", "verify_views_v4"),
    (5, "005_candidate_separation.sql", "候选/事实分离、外键修复", "verify_candidates_v5"),
    (6, "006_schema_contract_repair.sql", "修复已登记但结构缺失的 v5 数据库", "verify_schema_contract_v6"),
    (7, "007_candidate_nullable_contract.sql", "修复候选模型与表约束冲突", "verify_candidate_contract_v7"),
    (8, "008_trustworthy_views.sql", "收紧可信事实出口链路", "verify_trustworthy_views_v8"),
    (9, "009_source_discovery_ledger.sql", "添加来源发现候选台账", "verify_source_discovery_ledger_v9"),
    (10, "010_source_discovery_probe.sql", "添加来源候选访问探测", "verify_source_discovery_probe_v10"),
    (11, "011_intelligent_task_plans.sql", "添加智能任务规划台账", "verify_intelligent_task_plans_v11"),
]

CURRENT_VERSION = max(v for v, _, _, _ in MIGRATIONS)


def _applied_version(conn: sqlite3.Connection) -> int:
    """返回已应用的最高 schema 版本；表不存在视为 0。"""
    try:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None or row["v"] is None:
        return 0
    return int(row["v"])


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """检查表中是否存在指定列（D15修复）。"""
    try:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]
        return column in columns
    except sqlite3.OperationalError:
        return False


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """检查表是否存在。"""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    )
    return cursor.fetchone() is not None


def _view_exists(conn: sqlite3.Connection, view: str) -> bool:
    """检查视图是否存在。"""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name=?",
        (view,)
    )
    return cursor.fetchone() is not None


def _index_exists(conn: sqlite3.Connection, index: str) -> bool:
    """检查索引是否存在。"""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index,),
    )
    return cursor.fetchone() is not None


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    """以单列为单位补齐历史数据库结构。

    SQLite 不支持 ``ADD COLUMN IF NOT EXISTS``。单独判断并执行可避免旧的
    ``executescript`` 在第一条 duplicate-column 错误后跳过余下语句。
    """
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN [{column}] {declaration}")


# ============================================================
# 迁移验证函数（D15修复）
# ============================================================

def verify_sources_v2(conn: sqlite3.Connection) -> tuple[bool, str]:
    """验证 v2 迁移是否完整（sources 表扩展）。"""
    required_columns = ['entity_id', 'entity_type', 'canonical_url',
                       'document_type', 'source_reliability_score', 'covered_metric']

    missing = []
    for col in required_columns:
        if not _column_exists(conn, 'sources', col):
            missing.append(col)

    if missing:
        return False, f"sources 表缺少列: {', '.join(missing)}"

    return True, "sources 表结构完整"


def verify_links_v3(conn: sqlite3.Connection) -> tuple[bool, str]:
    """验证 v3 迁移是否完整（项目-电站关联）。"""
    if not _table_exists(conn, 'project_station_links'):
        return False, "project_station_links 表不存在"

    if not _table_exists(conn, 'project_status_history'):
        return False, "project_status_history 表不存在"

    return True, "项目关联表结构完整"


def verify_views_v4(conn: sqlite3.Connection) -> tuple[bool, str]:
    """验证 v4 迁移是否完整（Products 视图）。"""
    if not _view_exists(conn, 'v_top100_generation'):
        return False, "v_top100_generation 视图不存在"

    if not _view_exists(conn, 'v_data_coverage'):
        return False, "v_data_coverage 视图不存在"

    return True, "Products 视图结构完整"


def verify_candidates_v5(conn: sqlite3.Connection) -> tuple[bool, str]:
    """验证 v5 迁移是否完整（候选分离）。"""
    # 检查新表
    required_tables = [
        'extraction_candidates',
        'candidate_evidence',
        'review_events',
        'generation_record_history'
    ]

    for table in required_tables:
        if not _table_exists(conn, table):
            return False, f"{table} 表不存在"

    # 检查 generation_records 的新列
    if not _column_exists(conn, 'generation_records', 'candidate_id'):
        return False, "generation_records 缺少 candidate_id 列"

    # sources 的 v5 列可能在 v2 已添加，不强制要求
    # 只记录状态，不作为失败条件
    v5_columns = ['entity_type', 'canonical_url', 'document_type', 'covered_metric']
    missing = []
    for col in v5_columns:
        if not _column_exists(conn, 'sources', col):
            missing.append(col)

    if missing:
        logger.warning(f"sources 表缺少部分 v5 列（非关键）: {', '.join(missing)}")

    return True, "v5 候选分离核心结构完整"


def verify_schema_contract_v6(conn: sqlite3.Connection) -> tuple[bool, str]:
    """验证 V4 计划要求的 v6 最小结构契约。"""
    required_columns = {
        "tasks": ("source_type", "user_specified_source"),
        "review_items": ("candidate_id",),
        "extraction_candidates": ("review_status",),
        "generation_records": ("candidate_id",),
    }
    for table, columns in required_columns.items():
        if not _table_exists(conn, table):
            return False, f"{table} 表不存在"
        missing = [column for column in columns if not _column_exists(conn, table, column)]
        if missing:
            return False, f"{table} 表缺少列: {', '.join(missing)}"

    required_tables = (
        "candidate_evidence",
        "review_events",
        "generation_record_history",
    )
    for table in required_tables:
        if not _table_exists(conn, table):
            return False, f"{table} 表不存在"

    required_indexes = (
        "idx_tasks_source_type",
        "idx_review_candidate_v6",
        "idx_candidates_review_status_v6",
    )
    missing_indexes = [index for index in required_indexes if not _index_exists(conn, index)]
    if missing_indexes:
        return False, f"缺少索引: {', '.join(missing_indexes)}"

    required_views = ("v_top100_generation", "v_data_coverage")
    missing_views = [view for view in required_views if not _view_exists(conn, view)]
    if missing_views:
        return False, f"缺少视图: {', '.join(missing_views)}"

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        return False, f"外键检查失败: {len(violations)} 项"

    return True, "v6 结构契约完整"


def _repair_schema_contract_v6(conn: sqlite3.Connection) -> None:
    """执行 v6 的结构化、可回滚纠偏迁移。

    本函数只补齐当前源码实际依赖的结构，不修改历史迁移文件，也不清理
    业务数据。缺少基础表时明确失败，避免在错误数据库上“伪造成功”。
    """
    required_tables = (
        "tasks",
        "review_items",
        "extraction_candidates",
        "generation_records",
        "candidate_evidence",
        "review_events",
        "generation_record_history",
    )
    missing_tables = [table for table in required_tables if not _table_exists(conn, table)]
    if missing_tables:
        raise RuntimeError(f"无法修复的历史数据库，缺少基础表: {', '.join(missing_tables)}")

    # 每个操作单独判断，避免 duplicate-column 中断后续修复。
    _add_column_if_missing(conn, "tasks", "source_type", "TEXT DEFAULT 'automatic'")
    _add_column_if_missing(conn, "tasks", "user_specified_source", "TEXT")
    _add_column_if_missing(conn, "review_items", "candidate_id", "TEXT")
    _add_column_if_missing(
        conn,
        "extraction_candidates",
        "review_status",
        "TEXT NOT NULL DEFAULT 'pending'",
    )
    _add_column_if_missing(conn, "generation_records", "candidate_id", "TEXT")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_source_type ON tasks(source_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_candidate_v6 ON review_items(candidate_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidates_review_status_v6 "
        "ON extraction_candidates(review_status)"
    )

    # 历史主库存在 v5 已登记、但 v4 Products 视图未实际创建的情况。
    # 仅在缺失时补建，避免本阶段改写既有可信查询定义；严格过滤规则在阶段 8
    # 统一收敛。
    if not _view_exists(conn, "v_data_coverage"):
        conn.execute(
            "CREATE VIEW v_data_coverage AS "
            "SELECT s.country, r.period_label AS year, "
            "COUNT(DISTINCT r.entity_id) AS stations_with_data, "
            "COUNT(DISTINCT s.entity_id) AS total_stations, "
            "ROUND(100.0 * COUNT(DISTINCT r.entity_id) / "
            "NULLIF(COUNT(DISTINCT s.entity_id), 0), 1) AS coverage_percent "
            "FROM stations s LEFT JOIN generation_records r "
            "ON s.entity_id = r.entity_id "
            "AND r.publication_status = 'publishable' "
            "AND r.review_status = 'approved' "
            "AND r.value_type = 'actual' "
            "GROUP BY s.country, r.period_label"
        )


def verify_candidate_contract_v7(conn: sqlite3.Connection) -> tuple[bool, str]:
    """候选层允许未知分类进入复核，不能用 NOT NULL 把它们静默丢弃。"""
    success, message = verify_schema_contract_v6(conn)
    if not success:
        return False, message
    columns = {
        row[1]: row for row in conn.execute("PRAGMA table_info(extraction_candidates)")
    }
    nullable = ("period_type", "period_label", "value_type", "measurement_scope")
    missing = [name for name in nullable if name not in columns]
    if missing:
        return False, f"extraction_candidates 缺少列: {', '.join(missing)}"
    constrained = [name for name in nullable if columns[name][3]]
    if constrained:
        return False, f"候选不确定字段仍被 NOT NULL 阻断: {', '.join(constrained)}"
    return True, "v7 候选可复核契约完整"


def _repair_candidate_contract_v7(conn: sqlite3.Connection) -> int | None:
    """重建候选表以放宽抽取阶段未知字段，保留全部既有数据和外键关系。"""
    if not _table_exists(conn, "extraction_candidates"):
        raise RuntimeError("无法修复候选契约：extraction_candidates 表不存在")

    columns = {
        row[1]: row for row in conn.execute("PRAGMA table_info(extraction_candidates)")
    }
    nullable = ("period_type", "period_label", "value_type", "measurement_scope")
    if all(name in columns and not columns[name][3] for name in nullable):
        return None

    # 该表被 candidate_evidence/review_events/history 引用。SQLite 只能通过重建
    # 放宽 NOT NULL；迁移期间暂关 FK，结束后立即完整校验，任何异常都恢复开关。
    fk_enabled = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""
            CREATE TABLE extraction_candidates_v7 (
                candidate_id TEXT PRIMARY KEY,
                task_id TEXT,
                entity_id TEXT,
                document_id TEXT NOT NULL,
                period_type TEXT,
                period_label TEXT,
                value_type TEXT,
                measurement_scope TEXT,
                generation_gwh REAL,
                value_raw TEXT,
                unit_raw TEXT,
                snippet TEXT,
                extraction_method TEXT,
                extracted_at TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY (entity_id) REFERENCES stations(entity_id),
                FOREIGN KEY (document_id) REFERENCES documents(document_id),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
        """)
    conn.execute("""
            INSERT INTO extraction_candidates_v7 (
                candidate_id, task_id, entity_id, document_id,
                period_type, period_label, value_type, measurement_scope,
                generation_gwh, value_raw, unit_raw, snippet,
                extraction_method, extracted_at, review_status
            )
            SELECT candidate_id, task_id, entity_id, document_id,
                   period_type, period_label, value_type, measurement_scope,
                   generation_gwh, value_raw, unit_raw, snippet,
                   extraction_method, extracted_at, review_status
            FROM extraction_candidates
        """)
    conn.execute("DROP TABLE extraction_candidates")
    conn.execute("ALTER TABLE extraction_candidates_v7 RENAME TO extraction_candidates")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_entity ON extraction_candidates(entity_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_task ON extraction_candidates(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_document ON extraction_candidates(document_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidates_review_status_v6 "
        "ON extraction_candidates(review_status)"
    )
    return fk_enabled


def _execute_v7_candidate_contract_repair(conn: sqlite3.Connection, version: int) -> None:
    """v7 整体迁移必须在已提交状态运行，避免 SQLite 忽略 foreign_keys 切换。"""
    conn.commit()
    fk_enabled: int | None = None
    try:
        fk_enabled = _repair_candidate_contract_v7(conn)
        # PRAGMA foreign_keys 只能在事务外生效，因此必须先提交重建结果。
        conn.commit()
        if fk_enabled is not None:
            conn.execute(f"PRAGMA foreign_keys = {fk_enabled}")
        success, message = verify_candidate_contract_v7(conn)
        if not success:
            raise RuntimeError(f"迁移 v7 验证失败: {message}")
        conn.execute(
            "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
            (version, now_iso()),
        )
    except Exception:
        conn.rollback()
        if fk_enabled is not None:
            conn.execute(f"PRAGMA foreign_keys = {fk_enabled}")
        raise


def verify_trustworthy_views_v8(conn: sqlite3.Connection) -> tuple[bool, str]:
    """验证所有数据库视图出口都包含候选—证据—文档完整链路。"""
    success, message = verify_candidate_contract_v7(conn)
    if not success:
        return False, message
    for view in ("v_top100_generation", "v_data_coverage"):
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (view,)
        ).fetchone()
        if not row:
            return False, f"视图不存在: {view}"
        sql = (row[0] or "").lower()
        if (
            "candidate_evidence" not in sql
            or "documents" not in sql
            or "c.entity_id = r.entity_id" not in sql
            or "c.generation_gwh = r.generation_gwh" not in sql
        ):
            return False, f"视图 {view} 未执行完整证据链过滤"
    return True, "v8 可信出口视图完整"


def verify_source_discovery_ledger_v9(conn: sqlite3.Connection) -> tuple[bool, str]:
    """验证发现候选被隔离在台账，而非混入可信 sources。"""
    success, message = verify_trustworthy_views_v8(conn)
    if not success:
        return False, message
    if not _table_exists(conn, "source_discoveries"):
        return False, "source_discoveries 表不存在"
    required = (
        "discovery_id", "entity_id", "candidate_url", "canonical_url",
        "discovery_method", "combined_score", "status", "discovered_at",
    )
    missing = [name for name in required if not _column_exists(conn, "source_discoveries", name)]
    if missing:
        return False, f"source_discoveries 缺少列: {', '.join(missing)}"
    indexes = ("idx_source_discoveries_entity", "idx_source_discoveries_status")
    missing_indexes = [name for name in indexes if not _index_exists(conn, name)]
    if missing_indexes:
        return False, f"source_discoveries 缺少索引: {', '.join(missing_indexes)}"
    return True, "v9 来源发现台账完整"


def verify_source_discovery_probe_v10(conn: sqlite3.Connection) -> tuple[bool, str]:
    """验证来源候选拥有访问探测结果。"""
    success, message = verify_source_discovery_ledger_v9(conn)
    if not success:
        return False, message
    required = ("access_status", "http_status", "final_url", "checked_at")
    missing = [name for name in required if not _column_exists(conn, "source_discoveries", name)]
    if missing:
        return False, f"source_discoveries 缺少访问探测列: {', '.join(missing)}"
    if not _index_exists(conn, "idx_source_discoveries_access"):
        return False, "source_discoveries 缺少访问探测索引"
    return True, "v10 来源候选访问探测结构完整"


def verify_intelligent_task_plans_v11(conn: sqlite3.Connection) -> tuple[bool, str]:
    """验证自然语言任务只写入规划台账，不直接污染事实链路。"""
    success, message = verify_source_discovery_probe_v10(conn)
    if not success:
        return False, message
    for table in ("intelligent_task_plans", "intelligent_task_events"):
        if not _table_exists(conn, table):
            return False, f"{table} 表不存在"
    required = ("plan_id", "user_prompt", "entity_id", "status", "intent_json", "created_at")
    missing = [name for name in required if not _column_exists(conn, "intelligent_task_plans", name)]
    if missing:
        return False, f"intelligent_task_plans 缺少列: {', '.join(missing)}"
    indexes = ("idx_intelligent_task_plans_status", "idx_intelligent_task_events_plan")
    missing_indexes = [name for name in indexes if not _index_exists(conn, name)]
    if missing_indexes:
        return False, f"智能任务台账缺少索引: {', '.join(missing_indexes)}"
    return True, "v11 智能任务规划台账完整"


def _execute_v8_trustworthy_views(conn: sqlite3.Connection, version: int) -> None:
    """重建两个出口视图，统一执行 Candidate→Evidence→Document 链路校验。"""
    conn.execute("SAVEPOINT migration_v8")
    try:
        conn.execute("DROP VIEW IF EXISTS v_top100_generation")
        conn.execute("DROP VIEW IF EXISTS v_data_coverage")
        conn.execute("""
            CREATE VIEW v_top100_generation AS
            SELECT r.entity_id, s.canonical_name, s.country, s.region,
                   s.capacity_mw, r.period_label AS year, r.generation_gwh,
                   r.unit_raw, r.confidence, r.source_id, r.evidence_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY r.period_label ORDER BY r.generation_gwh DESC
                   ) AS rank
            FROM generation_records r
            JOIN stations s ON s.entity_id = r.entity_id
            JOIN extraction_candidates c
              ON c.candidate_id = r.candidate_id
             AND c.entity_id = r.entity_id
             AND c.period_type = r.period_type
             AND c.period_label = r.period_label
             AND c.value_type = r.value_type
             AND c.measurement_scope = r.measurement_scope
             AND c.generation_gwh = r.generation_gwh
            JOIN candidate_evidence ce
              ON ce.candidate_id = c.candidate_id AND ce.evidence_id = r.evidence_id
            JOIN evidence e ON e.evidence_id = r.evidence_id
            JOIN documents d
              ON d.document_id = c.document_id
             AND d.document_id = e.document_id
             AND d.content_hash = e.content_hash
            WHERE r.value_type = 'actual'
              AND r.period_type = 'calendar_year'
              AND r.measurement_scope = 'plant'
              AND r.validation_status = 'passed'
              AND r.review_status = 'approved'
              AND r.publication_status = 'publishable'
        """)
        conn.execute("""
            CREATE VIEW v_data_coverage AS
            SELECT s.country, r.period_label AS year,
                   COUNT(DISTINCT r.entity_id) AS stations_with_data,
                   COUNT(DISTINCT s.entity_id) AS total_stations,
                   ROUND(100.0 * COUNT(DISTINCT r.entity_id) /
                         NULLIF(COUNT(DISTINCT s.entity_id), 0), 1) AS coverage_percent
            FROM stations s
            LEFT JOIN generation_records r
              ON r.entity_id = s.entity_id
             AND r.value_type = 'actual'
             AND r.period_type = 'calendar_year'
             AND r.measurement_scope = 'plant'
             AND r.validation_status = 'passed'
             AND r.review_status = 'approved'
             AND r.publication_status = 'publishable'
             AND EXISTS (
                 SELECT 1
                 FROM extraction_candidates c
                 JOIN candidate_evidence ce
                   ON ce.candidate_id = c.candidate_id AND ce.evidence_id = r.evidence_id
                 JOIN evidence e ON e.evidence_id = r.evidence_id
                 JOIN documents d
                   ON d.document_id = c.document_id
                  AND d.document_id = e.document_id
                  AND d.content_hash = e.content_hash
                 WHERE c.candidate_id = r.candidate_id
                   AND c.entity_id = r.entity_id
                   AND c.period_type = r.period_type
                   AND c.period_label = r.period_label
                   AND c.value_type = r.value_type
                   AND c.measurement_scope = r.measurement_scope
                   AND c.generation_gwh = r.generation_gwh
             )
            GROUP BY s.country, r.period_label
        """)
        success, message = verify_trustworthy_views_v8(conn)
        if not success:
            raise RuntimeError(f"迁移 v8 验证失败: {message}")
        conn.execute(
            "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
            (version, now_iso()),
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT migration_v8")
        conn.execute("RELEASE SAVEPOINT migration_v8")
        raise
    else:
        conn.execute("RELEASE SAVEPOINT migration_v8")


def _execute_v6_contract_repair(conn: sqlite3.Connection, version: int) -> None:
    """以 SAVEPOINT 保证 v6 不会留下半迁移状态。"""
    conn.execute("SAVEPOINT migration_v6")
    try:
        _repair_schema_contract_v6(conn)
        success, message = verify_schema_contract_v6(conn)
        if not success:
            raise RuntimeError(f"迁移 v6 验证失败: {message}")
        conn.execute(
            "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
            (version, now_iso()),
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT migration_v6")
        conn.execute("RELEASE SAVEPOINT migration_v6")
        raise
    else:
        conn.execute("RELEASE SAVEPOINT migration_v6")


# 验证函数映射
VERIFY_FUNCTIONS = {
    'verify_sources_v2': verify_sources_v2,
    'verify_links_v3': verify_links_v3,
    'verify_views_v4': verify_views_v4,
    'verify_candidates_v5': verify_candidates_v5,
    'verify_schema_contract_v6': verify_schema_contract_v6,
    'verify_candidate_contract_v7': verify_candidate_contract_v7,
    'verify_trustworthy_views_v8': verify_trustworthy_views_v8,
    'verify_source_discovery_ledger_v9': verify_source_discovery_ledger_v9,
    'verify_source_discovery_probe_v10': verify_source_discovery_probe_v10,
    'verify_intelligent_task_plans_v11': verify_intelligent_task_plans_v11,
}


def _execute_migration(
    conn: sqlite3.Connection,
    version: int,
    filename: str | None,
    description: str,
    verify_func_name: Optional[str]
) -> None:
    """执行单个迁移并验证结果（D15修复）。"""
    if version == 6:
        _execute_v6_contract_repair(conn, version)
        logger.info("✓ 迁移 v6 完成：结构契约完整")
        return
    if version == 7:
        _execute_v7_candidate_contract_repair(conn, version)
        logger.info("✓ 迁移 v7 完成：候选可复核契约完整")
        return
    if version == 8:
        _execute_v8_trustworthy_views(conn, version)
        logger.info("✓ 迁移 v8 完成：可信出口视图完整")
        return

    if filename is None:
        # 版本 1：执行初始 schema
        sql_path = SCHEMA_FILE
    else:
        # 其他版本：执行迁移文件
        sql_path = MIGRATIONS_DIR / filename

    if not sql_path.exists():
        raise FileNotFoundError(f"迁移文件不存在: {sql_path}")

    logger.info(f"执行迁移 v{version}: {description}")
    sql = sql_path.read_text(encoding="utf-8")

    # 执行SQL
    errors = []
    try:
        conn.executescript(sql)
    except sqlite3.OperationalError as e:
        # 某些 ALTER TABLE 操作可能因列已存在而失败
        if "duplicate column name" in str(e).lower():
            logger.warning(f"迁移 v{version} 部分语句已应用: {e}")
            errors.append(str(e))
        else:
            logger.error(f"迁移 v{version} 执行失败: {e}")
            raise

    # D15修复：验证迁移结果
    if verify_func_name and verify_func_name in VERIFY_FUNCTIONS:
        verify_func = VERIFY_FUNCTIONS[verify_func_name]
        success, message = verify_func(conn)

        if not success:
            error_msg = f"迁移 v{version} 验证失败: {message}"
            if errors:
                error_msg += f"\n执行时警告: {'; '.join(errors)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        else:
            logger.info(f"✓ 迁移 v{version} 验证通过: {message}")

    # 记录迁移版本
    conn.execute(
        "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
        (version, now_iso()),
    )
    logger.info(f"✓ 迁移 v{version} 完成")


def migrate(conn: sqlite3.Connection, target_version: Optional[int] = None) -> int:
    """将数据库迁移到目标版本（默认最新版本）。

    Args:
        conn: 数据库连接
        target_version: 目标版本（None=最新版本）

    Returns:
        迁移后的版本号

    Raises:
        RuntimeError: 迁移失败且验证不通过
    """
    if target_version is None:
        target_version = CURRENT_VERSION

    current = _applied_version(conn)

    if current >= target_version:
        if target_version >= 11:
            success, message = verify_intelligent_task_plans_v11(conn)
            contract_name = "v11"
        elif target_version >= 10:
            success, message = verify_source_discovery_probe_v10(conn)
            contract_name = "v10"
        elif target_version >= 9:
            success, message = verify_source_discovery_ledger_v9(conn)
            contract_name = "v9"
        elif target_version >= 8:
            success, message = verify_trustworthy_views_v8(conn)
            contract_name = "v8"
            # v8 视图定义可在源码中收紧；已有 v8 数据库需要自修复视图，
            # 不能只看版本号就继续使用旧出口。
            if not success and current == target_version == 8:
                _execute_v8_trustworthy_views(conn, 8)
                conn.commit()
                success, message = verify_trustworthy_views_v8(conn)
        elif target_version >= 7:
            success, message = verify_candidate_contract_v7(conn)
            contract_name = "v7"
        elif target_version >= 6:
            success, message = verify_schema_contract_v6(conn)
            contract_name = "v6"
        else:
            success, message, contract_name = True, "", ""
        if not success:
            raise RuntimeError(
                f"schema 版本为 v{current}，但实际结构不符合 {contract_name} 契约: {message}"
            )
        logger.info(f"schema 已是目标版本 v{current}，结构验证通过")
        return current

    logger.info(f"开始迁移：v{current} -> v{target_version}")

    # 执行所有未应用的迁移
    for version, filename, description, verify_func in MIGRATIONS:
        if current < version <= target_version:
            _execute_migration(conn, version, filename, description, verify_func)
            conn.commit()  # 每个迁移单独提交

    final_version = _applied_version(conn)

    if final_version < target_version:
        raise RuntimeError(
            f"迁移未达到目标版本: 当前={final_version}, 目标={target_version}"
        )

    logger.info(f"迁移完成：v{current} -> v{final_version}")

    return final_version
