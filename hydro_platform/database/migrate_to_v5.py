"""数据库迁移和修复工具（DB-Foundation 任务）。

功能：
1. 执行 v4 → v5 迁移
2. 修复外键违规（D13）
3. 验证迁移完整性（D15）
4. 生成迁移报告

用法：
    python -m hydro_platform.database.migrate_to_v5
"""

import shutil
import sqlite3
from pathlib import Path
from datetime import datetime

from hydro_platform.common.logging_setup import get_logger
from hydro_platform.database.connection_manager import get_manager
from hydro_platform.database.migrations import migrate, _applied_version
from hydro_platform.config.paths import get_database_path

logger = get_logger(__name__)


def backup_database(db_path: Path) -> Path:
    """备份数据库文件。"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = db_path.parent / f"{db_path.stem}_backup_{timestamp}{db_path.suffix}"

    logger.info(f"备份数据库: {db_path} -> {backup_path}")
    shutil.copy2(db_path, backup_path)

    return backup_path


def check_foreign_key_violations(conn: sqlite3.Connection) -> list:
    """检查外键违规。"""
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()

    return [
        {
            "table": row[0],
            "rowid": row[1],
            "parent_table": row[2],
            "fkid": row[3]
        }
        for row in violations
    ]


def fix_foreign_key_violations(conn: sqlite3.Connection) -> dict:
    """修复外键违规（D13）。

    Returns:
        修复统计信息
    """
    stats = {
        "violations_found": 0,
        "records_deleted": 0,
        "tables_affected": set()
    }

    # 检查违规
    violations = check_foreign_key_violations(conn)
    stats["violations_found"] = len(violations)

    if not violations:
        logger.info("未发现外键违规")
        return stats

    logger.warning(f"发现 {len(violations)} 处外键违规")

    # 按表分组
    by_table = {}
    for v in violations:
        table = v["table"]
        if table not in by_table:
            by_table[table] = []
        by_table[table].append(v)

    # 删除违规记录
    for table, items in by_table.items():
        rowids = [item["rowid"] for item in items]

        logger.warning(
            f"删除 {table} 表中 {len(rowids)} 条违规记录: "
            f"rowids={rowids}"
        )

        # 删除记录
        placeholders = ','.join('?' * len(rowids))
        conn.execute(
            f"DELETE FROM {table} WHERE rowid IN ({placeholders})",
            rowids
        )

        stats["records_deleted"] += len(rowids)
        stats["tables_affected"].add(table)

    conn.commit()

    # 再次检查
    remaining = check_foreign_key_violations(conn)
    if remaining:
        logger.error(f"修复后仍有 {len(remaining)} 处违规")
        for v in remaining:
            logger.error(f"  {v}")
    else:
        logger.info("✓ 所有外键违规已修复")

    stats["tables_affected"] = list(stats["tables_affected"])
    return stats


def run_migration(data_mode: str = "production") -> dict:
    """执行完整的 DB-Foundation 迁移流程。

    Args:
        data_mode: "production" 或 "test"

    Returns:
        迁移报告
    """
    report = {
        "data_mode": data_mode,
        "started_at": datetime.now().isoformat(),
        "backup_path": None,
        "initial_version": None,
        "final_version": None,
        "foreign_key_fixes": None,
        "success": False,
        "error": None
    }

    try:
        # 1. 获取连接管理器
        manager = get_manager(data_mode)
        db_path = get_database_path(data_mode)

        logger.info(f"开始 DB-Foundation 迁移: {db_path}")

        # 2. 检查当前版本
        conn = manager.get_connection(verify_foreign_keys=False)
        initial_version = _applied_version(conn)
        report["initial_version"] = initial_version

        logger.info(f"当前 schema 版本: v{initial_version}")

        # 3. 备份数据库
        if db_path.exists():
            backup_path = backup_database(db_path)
            report["backup_path"] = str(backup_path)

        # 4. 修复外键违规（在迁移前）
        logger.info("步骤 1/2: 修复外键违规")
        fk_fixes = fix_foreign_key_violations(conn)
        report["foreign_key_fixes"] = fk_fixes

        # 5. 执行迁移
        logger.info("步骤 2/2: 执行 schema 迁移")
        final_version = migrate(conn, target_version=5)
        report["final_version"] = final_version

        # 6. 最终验证
        remaining_violations = check_foreign_key_violations(conn)
        if remaining_violations:
            raise RuntimeError(
                f"迁移后仍有 {len(remaining_violations)} 处外键违规"
            )

        conn.close()

        report["success"] = True
        report["finished_at"] = datetime.now().isoformat()

        logger.info("=" * 60)
        logger.info("✓ DB-Foundation 迁移完成")
        logger.info(f"  版本: v{initial_version} → v{final_version}")
        logger.info(f"  外键修复: {fk_fixes['records_deleted']} 条记录删除")
        logger.info(f"  备份: {report['backup_path']}")
        logger.info("=" * 60)

        return report

    except Exception as e:
        logger.error(f"迁移失败: {e}", exc_info=True)
        report["success"] = False
        report["error"] = str(e)
        report["finished_at"] = datetime.now().isoformat()
        raise


def main():
    """命令行入口。"""
    import sys

    data_mode = sys.argv[1] if len(sys.argv) > 1 else "production"

    print(f"\n{'='*60}")
    print(f"DB-Foundation 迁移工具")
    print(f"数据模式: {data_mode}")
    print(f"{'='*60}\n")

    try:
        report = run_migration(data_mode)

        print("\n迁移报告:")
        print(f"  初始版本: v{report['initial_version']}")
        print(f"  最终版本: v{report['final_version']}")
        print(f"  外键修复: {report['foreign_key_fixes']['records_deleted']} 条")
        print(f"  备份路径: {report['backup_path']}")
        print(f"  结果: {'成功' if report['success'] else '失败'}")

        if report['success']:
            print("\n[OK] 迁移成功完成")
            sys.exit(0)
        else:
            print(f"\n[FAIL] 迁移失败: {report['error']}")
            sys.exit(1)

    except Exception as e:
        print(f"\n[FAIL] 迁移失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
