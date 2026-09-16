"""SQLite 连接管理。

统一开启：外键约束、WAL 模式（并发读友好）、Row 工厂（按列名取值）。
提供 connect() 与 transaction() 上下文管理器，封装提交/回滚边界。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..common.exceptions import DatabaseError
from ..config import paths

DEFAULT_TIMEOUT_SECONDS = 30.0


def connect(
    db_path: Path | None = None,
    *,
    read_only: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> sqlite3.Connection:
    """建立 SQLite 连接并应用统一 PRAGMA。

    db_path 为空时使用 config.paths.db_path()；读写连接会自动创建父目录。
    ``read_only=True`` 用 SQLite URI 打开只读快照，不执行可能争抢写锁的
    WAL 设置，供 GUI 的查询路径访问已有正式库。
    """
    target = db_path or paths.db_path()
    target = Path(target)
    if not read_only:
        target.parent.mkdir(parents=True, exist_ok=True)
    elif not target.exists():
        raise DatabaseError(f"只读数据库不存在: {target}")

    try:
        if read_only:
            # Windows 盘符路径必须使用标准 file:/// URI；原来的 ``file:F:/...``
            # 会被 SQLite 当成相对 URI，导致正式库的只读查询无法打开。
            uri = f"{target.resolve().as_uri()}?mode=ro"
            try:
                conn = None
                conn = sqlite3.connect(
                    uri,
                    uri=True,
                    check_same_thread=False,
                    timeout=timeout,
                )
                # Windows 某些跨盘文件系统会延迟到第一次读表时才暴露
                # “unable to open database file”；提前读 schema_version，
                # 让下面的 immutable 回退覆盖这类懒加载失败。
                conn.execute("PRAGMA schema_version").fetchone()
            except sqlite3.OperationalError:
                # 某些 Windows/跨盘文件系统无法建立 SQLite 只读锁，即使
                # 数据库本身是完整且稳定的；此时在没有任何 journal/WAL
                # 旁文件的前提下，immutable 仍是安全的只读快照。若存在
                # WAL/journal，必须保留原错误，避免读到过期快照。
                sidecars = (
                    target.with_name(target.name + "-wal"),
                    target.with_name(target.name + "-shm"),
                    target.with_name(target.name + "-journal"),
                )
                if any(path.exists() for path in sidecars):
                    if conn is not None:
                        conn.close()
                    raise
                if conn is not None:
                    conn.close()
                immutable_uri = f"{target.resolve().as_uri()}?mode=ro&immutable=1"
                conn = sqlite3.connect(
                    immutable_uri,
                    uri=True,
                    check_same_thread=False,
                    timeout=timeout,
                )
        else:
            conn = sqlite3.connect(
                str(target),
                check_same_thread=False,
                timeout=timeout,
            )
    except sqlite3.Error as exc:  # pragma: no cover - 连接级异常罕见
        raise DatabaseError(f"无法连接数据库 {target}：{exc}") from exc
    conn.row_factory = sqlite3.Row
    # ``timeout`` 只设置驱动默认值；显式 PRAGMA 让运行时和验收都能观察
    # 到同一套等待策略，避免并发 API 把瞬时锁竞争暴露给前端。
    conn.execute(f"PRAGMA busy_timeout = {max(0, int(timeout * 1000))}")
    conn.execute("PRAGMA foreign_keys = ON")
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """事务上下文：正常退出提交，异常回滚后重抛。"""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
