"""统一数据库连接管理器（D14/D15修复）。

解决问题：
- D14: API 数据库连接未启用外键约束
- D15: 多个模块使用不同的连接方式
- 统一连接配置、外键检查、WAL模式

所有数据库访问应通过此模块获取连接。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from ..common.exceptions import DatabaseError
from ..common.logging_setup import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """数据库连接管理器：统一连接配置和验证。"""

    def __init__(self, db_path: Path):
        """初始化连接管理器。

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._active_connections = []

    def get_connection(self, verify_foreign_keys: bool = True) -> sqlite3.Connection:
        """获取配置好的数据库连接。

        Args:
            verify_foreign_keys: 是否验证外键已启用（默认True）

        Returns:
            已配置的 SQLite 连接

        Raises:
            DatabaseError: 连接失败或外键未启用
        """
        # 确保父目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
        except sqlite3.Error as exc:
            raise DatabaseError(f"无法连接数据库 {self.db_path}: {exc}") from exc

        # 配置连接
        conn.row_factory = sqlite3.Row
        # 显式设置忙等待时间；仅传 sqlite3 timeout 不足以形成可审计的
        # 连接契约，前端并发读写时也容易把瞬时竞争暴露成 database is locked。
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")

        # D14修复：验证外键确实已启用
        if verify_foreign_keys:
            fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            if fk_status != 1:
                conn.close()
                raise DatabaseError(
                    f"外键约束启用失败 (PRAGMA foreign_keys = {fk_status}), "
                    f"数据库: {self.db_path}"
                )

        # 跟踪活动连接（用于调试和清理）
        self._active_connections.append(conn)

        return conn

    @contextmanager
    def transaction(
        self,
        conn: Optional[sqlite3.Connection] = None
    ) -> Iterator[sqlite3.Connection]:
        """事务上下文管理器。

        Args:
            conn: 已有连接（可选）。如果为None，会创建新连接

        Yields:
            数据库连接

        用法:
            with manager.transaction() as conn:
                conn.execute(...)
                # 成功时自动提交，异常时回滚
        """
        own_connection = conn is None
        if own_connection:
            conn = self.get_connection()

        try:
            yield conn
            if own_connection:
                conn.commit()
        except Exception:
            if own_connection:
                conn.rollback()
            raise
        finally:
            if own_connection:
                conn.close()
                self._active_connections.remove(conn)

    def check_foreign_key_violations(
        self,
        conn: Optional[sqlite3.Connection] = None
    ) -> list[dict]:
        """检查当前数据库的外键违规。

        Args:
            conn: 已有连接（可选）

        Returns:
            违规列表，每项包含: table, rowid, parent_table, fkid
        """
        own_connection = conn is None
        if own_connection:
            conn = self.get_connection()

        try:
            # 确保外键检查已启用
            conn.execute("PRAGMA foreign_keys = ON")

            violations = []
            for row in conn.execute("PRAGMA foreign_key_check").fetchall():
                violations.append({
                    "table": row[0],
                    "rowid": row[1],
                    "parent_table": row[2],
                    "fkid": row[3]
                })

            return violations
        finally:
            if own_connection:
                conn.close()
                self._active_connections.remove(conn)

    def close_all(self):
        """关闭所有活动连接（用于清理）。"""
        for conn in self._active_connections[:]:
            try:
                conn.close()
            except Exception as e:
                logger.warning(f"关闭连接时出错: {e}")
        self._active_connections.clear()


# 全局单例（按数据模式）
_managers = {}


def get_manager(data_mode: str = "production") -> ConnectionManager:
    """获取指定数据模式的连接管理器单例。

    Args:
        data_mode: "production" 或 "test"

    Returns:
        ConnectionManager 实例
    """
    from ..config.paths import get_database_path

    if data_mode not in _managers:
        db_path = get_database_path(data_mode)
        _managers[data_mode] = ConnectionManager(db_path)

    return _managers[data_mode]


def get_connection(data_mode: str = "production") -> sqlite3.Connection:
    """便捷函数：获取配置好的数据库连接。

    Args:
        data_mode: "production" 或 "test"

    Returns:
        已配置的 SQLite 连接
    """
    return get_manager(data_mode).get_connection()
