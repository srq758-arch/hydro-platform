"""数据访问层（Repository）。

封装各表的读写，向上层隐藏 SQL。所有写入走 upsert（ON CONFLICT），
保证幂等——重复导入同一 seed 不产生重复行（文档 23.1）。
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

from ..common.clock import now_iso
from ..common.enums import TaskStatus
from ..models.project import Project
from ..models.station import Station
from ..models.task import Task

# stations/projects 共享同一批列（两表结构一致，仅默认 entity_type 不同）
_ENTITY_COLUMNS = (
    "entity_id", "entity_type", "canonical_name", "aliases", "local_name",
    "country", "country_2", "region", "subregion", "state_province", "river",
    "latitude", "longitude", "location_accuracy", "capacity_mw", "turbines",
    "status", "technology", "operator", "owner", "commissioning_year",
    "gem_location_id", "gem_unit_id", "gem_wiki_url", "priority_tier",
    "collection_priority", "needs_review", "source_seed", "source_url",
    "dataset_version", "registry_version", "raw_record_hash",
)

# stations 表比 projects 多一列 retired_year（仅电站会退役）
_STATION_COLUMNS = _ENTITY_COLUMNS + ("retired_year",)


def _entity_row(model: Station | Project, columns: tuple[str, ...]) -> tuple:
    d = model.model_dump()
    return tuple(
        int(d[c]) if c == "needs_review" else _enum_value(d.get(c))
        for c in columns
    )


def _enum_value(v):
    """把枚举转成其字符串值，其余原样返回。"""
    return v.value if hasattr(v, "value") else v


def _upsert_sql(table: str, columns: tuple[str, ...], pk: str) -> str:
    cols = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c != pk)
    return (
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk}) DO UPDATE SET {updates}"
    )


class StationRepository:
    """stations 表读写。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_many(self, stations: Iterable[Station]) -> int:
        sql = _upsert_sql("stations", _STATION_COLUMNS, "entity_id")
        rows = [_entity_row(s, _STATION_COLUMNS) for s in stations]
        self.conn.executemany(sql, rows)
        return len(rows)

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0])

    def get(self, entity_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM stations WHERE entity_id = ?", (entity_id,)
        ).fetchone()


class ProjectRepository:
    """projects 表读写。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_many(self, projects: Iterable[Project]) -> int:
        sql = _upsert_sql("projects", _ENTITY_COLUMNS, "entity_id")
        rows = [_entity_row(p, _ENTITY_COLUMNS) for p in projects]
        self.conn.executemany(sql, rows)
        return len(rows)

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])

    def get(self, entity_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM projects WHERE entity_id = ?", (entity_id,)
        ).fetchone()


_TASK_COLUMNS = (
    "task_id", "entity_id", "entity_type", "task_type", "target_period",
    "status", "priority_tier", "collection_priority", "attempts",
    "max_attempts", "failure_stage", "last_error", "source_type",
    "user_specified_source", "created_at", "updated_at",
)


def _task_row(t: Task) -> tuple:
    d = t.model_dump()
    return tuple(_enum_value(d.get(c)) for c in _TASK_COLUMNS)


class TaskRepository:
    """tasks 表读写。upsert 幂等键为 task_id（由三元组派生）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_many(self, tasks: Iterable[Task]) -> int:
        # 任务运行态由 TaskManager 状态机维护。重复建任务只能刷新静态元数据，
        # 不能把 success/running/failed、attempts 或失败审计重置回模型默认值。
        cols = _TASK_COLUMNS
        updates = ", ".join(
            f"{c}=excluded.{c}"
            for c in ("entity_id", "entity_type", "task_type", "target_period",
                      "priority_tier", "collection_priority", "updated_at")
        )
        updates += (
            ", source_type=CASE WHEN excluded.source_type='manual' "
            "THEN excluded.source_type ELSE tasks.source_type END"
            ", user_specified_source=CASE WHEN excluded.source_type='manual' "
            "THEN excluded.user_specified_source ELSE tasks.user_specified_source END"
        )
        placeholders = ", ".join("?" for _ in cols)
        sql = (
            f"INSERT INTO tasks ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(task_id) DO UPDATE SET {updates}"
        )
        rows = [_task_row(t) for t in tasks]
        self.conn.executemany(sql, rows)
        return len(rows)

    def fetch_by_status(self, status: str, limit: int | None = None) -> list[sqlite3.Row]:
        """按状态取任务，用于调度。tier + 优先级排序（tier 字典序近似 T1<T2<T3）。"""
        sql = (
            "SELECT * FROM tasks WHERE status = ? "
            "ORDER BY priority_tier ASC, collection_priority ASC"
        )
        params: tuple = (status,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (status, limit)
        return self.conn.execute(sql, params).fetchall()

    def update_status(
        self,
        task_id: str,
        status: str,
        *,
        failure_stage: str | None = None,
        last_error: str | None = None,
        bump_attempt: bool = False,
    ) -> None:
        """更新任务状态；bump_attempt=True 时 attempts +1。"""
        sets = ["status = ?", "updated_at = ?", "failure_stage = ?", "last_error = ?"]
        params: list = [status, now_iso(), failure_stage, last_error]
        if bump_attempt:
            sets.append("attempts = attempts + 1")
        if status != TaskStatus.RUNNING.value and self._lease_columns_available():
            sets.extend([
                "worker_id = NULL",
                "lease_expires_at = NULL",
                "heartbeat_at = NULL",
            ])
        self.conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?",
            (*params, task_id),
        )

    def _lease_columns_available(self) -> bool:
        """兼容尚未升级 v14 的现有数据库。"""
        columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        return {"worker_id", "lease_expires_at", "heartbeat_at"}.issubset(columns)

    def claim_if_pending(
        self,
        task_id: str,
        *,
        worker_id: str | None = None,
        lease_expires_at: str | None = None,
        heartbeat_at: str | None = None,
    ) -> bool:
        """原子执行 pending→running；仅一个竞争 worker 能成功。"""
        if self._lease_columns_available():
            cursor = self.conn.execute(
                """UPDATE tasks
                   SET status=?, updated_at=?, failure_stage=NULL, last_error=NULL,
                       worker_id=?, lease_expires_at=?, heartbeat_at=?
                   WHERE task_id=? AND status=?""",
                (
                    TaskStatus.RUNNING.value,
                    now_iso(),
                    worker_id,
                    lease_expires_at,
                    heartbeat_at,
                    task_id,
                    TaskStatus.PENDING.value,
                ),
            )
        else:
            cursor = self.conn.execute(
                """UPDATE tasks
                   SET status=?, updated_at=?, failure_stage=NULL, last_error=NULL
                   WHERE task_id=? AND status=?""",
                (
                    TaskStatus.RUNNING.value,
                    now_iso(),
                    task_id,
                    TaskStatus.PENDING.value,
                ),
            )
        return cursor.rowcount == 1

    def heartbeat_lease(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_expires_at: str,
        heartbeat_at: str,
    ) -> bool:
        """仅持有该租约的 running worker 可以续期。"""
        if not self._lease_columns_available():
            return False
        cursor = self.conn.execute(
            """UPDATE tasks
               SET lease_expires_at=?, heartbeat_at=?, updated_at=?
               WHERE task_id=? AND status=? AND worker_id=?""",
            (
                lease_expires_at,
                heartbeat_at,
                now_iso(),
                task_id,
                TaskStatus.RUNNING.value,
                worker_id,
            ),
        )
        return cursor.rowcount == 1

    def recover_expired_leases(self, *, before: str) -> list[str]:
        """把崩溃 worker 的过期 running 任务安全标为可重试失败。"""
        if not self._lease_columns_available():
            return []
        rows = self.conn.execute(
            """SELECT task_id FROM tasks
               WHERE status=? AND lease_expires_at IS NOT NULL
                 AND lease_expires_at < ?""",
            (TaskStatus.RUNNING.value, before),
        ).fetchall()
        task_ids = [row[0] for row in rows]
        if not task_ids:
            return []
        self.conn.executemany(
            """UPDATE tasks
               SET status=?, failure_stage=?,
                   last_error='任务租约已过期，等待受控重试',
                   attempts=attempts+1, updated_at=?, worker_id=NULL,
                   lease_expires_at=NULL, heartbeat_at=NULL
               WHERE task_id=? AND status=? AND lease_expires_at IS NOT NULL
                 AND lease_expires_at < ?""",
            [
                (
                    TaskStatus.FAILED.value,
                    "UNKNOWN",
                    now_iso(),
                    task_id,
                    TaskStatus.RUNNING.value,
                    before,
                )
                for task_id in task_ids
            ],
        )
        return task_ids

    def get(self, task_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])


_DOCUMENT_COLUMNS = (
    "document_id", "entity_id", "task_id", "source_id", "original_url",
    "final_url", "fetched_at", "published_at", "content_type", "content_kind",
    "file_size", "content_hash", "local_path", "access_method", "version",
    "created_at",
)


class DocumentRepository:
    """documents 表读写（文档 10.3）。

    幂等键为 document_id（URL + 内容哈希派生）：同一原始资料重复归档不重复入库、
    不覆盖既有行（原始资料不可覆盖）。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_if_absent(self, doc) -> bool:
        """归档一条文档元数据。已存在同 document_id 则跳过，返回 False。"""
        d = doc.model_dump()
        row = tuple(_enum_value(d.get(c)) for c in _DOCUMENT_COLUMNS)
        placeholders = ", ".join("?" for _ in _DOCUMENT_COLUMNS)
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO documents ({', '.join(_DOCUMENT_COLUMNS)}) "
            f"VALUES ({placeholders})",
            row,
        )
        return cur.rowcount > 0

    def get(self, document_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM documents WHERE document_id = ?", (document_id,)
        ).fetchone()

    def versions_for_url(self, original_url: str) -> list[sqlite3.Row]:
        """返回某 URL 已归档的所有版本，按 version 升序。"""
        return self.conn.execute(
            "SELECT * FROM documents WHERE original_url = ? ORDER BY version ASC",
            (original_url,),
        ).fetchall()

    def max_version_for_url(self, original_url: str) -> int:
        """返回某 URL 当前最高版本号；无记录返回 0。"""
        row = self.conn.execute(
            "SELECT MAX(version) AS v FROM documents WHERE original_url = ?",
            (original_url,),
        ).fetchone()
        if row is None or row["v"] is None:
            return 0
        return int(row["v"])

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])


class RegistryAuditRepository:
    """registry_audit 表写入：每次 seed 导入批次留一条痕迹（文档 23.1）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def record(
        self,
        *,
        registry_kind: str,
        registry_version: str | None,
        row_count: int,
        source_file: str | None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO registry_audit "
            "(registry_kind, registry_version, row_count, source_file, imported_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (registry_kind, registry_version, row_count, source_file, now_iso()),
        )

    def count(self) -> int:
        return int(
            self.conn.execute("SELECT COUNT(*) FROM registry_audit").fetchone()[0]
        )


_GENERATION_COLUMNS = (
    "entity_id", "period_type", "period_label", "generation_gwh", "value_type",
    "measurement_scope", "metric", "normalized_unit", "unit_raw", "value_raw", "source_id", "task_id",
    "evidence_id", "candidate_id", "confidence", "extractor", "validation_status",
    "review_status", "publication_status", "created_at", "updated_at",
)

_GEN_NATURAL_KEY = (
    "entity_id", "period_type", "period_label", "value_type", "measurement_scope",
)


class GenerationRepository:
    """generation_records 表读写（文档 16.2，正式发电量事实）。

    幂等键为自然键 (entity_id, period_type, period_label, value_type,
    measurement_scope)：同一事实重复升级更新而不新建。只有 publishable 记录
    进 Top100。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, values: dict) -> None:
        """按自然键幂等 upsert 一条正式记录。缺列以 None 填充。"""
        row = tuple(_enum_value(values.get(c)) for c in _GENERATION_COLUMNS)
        cols = ", ".join(_GENERATION_COLUMNS)
        placeholders = ", ".join("?" for _ in _GENERATION_COLUMNS)
        conflict = ", ".join(_GEN_NATURAL_KEY)
        updates = ", ".join(
            f"{c}=excluded.{c}"
            for c in _GENERATION_COLUMNS
            if c not in _GEN_NATURAL_KEY and c != "created_at"
        )
        self.conn.execute(
            f"INSERT INTO generation_records ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict}) DO UPDATE SET {updates}",
            row,
        )

    def get_by_key(
        self,
        *,
        entity_id: str,
        period_type: str,
        period_label: str,
        value_type: str,
        measurement_scope: str,
    ) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM generation_records WHERE entity_id=? AND period_type=? "
            "AND period_label=? AND value_type=? AND measurement_scope=?",
            (entity_id, period_type, period_label, value_type, measurement_scope),
        ).fetchone()

    def publishable(self, *, entity_id: str | None = None) -> list[sqlite3.Row]:
        """返回可进 Top100 的记录（publication_status='publishable'）。"""
        if entity_id is None:
            return self.conn.execute(
                "SELECT * FROM generation_records WHERE publication_status='publishable'"
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM generation_records "
            "WHERE publication_status='publishable' AND entity_id=?",
            (entity_id,),
        ).fetchall()

    def count(self) -> int:
        return int(
            self.conn.execute("SELECT COUNT(*) FROM generation_records").fetchone()[0]
        )


_SOURCE_COLUMNS = (
    "source_id", "url", "title", "publisher", "publish_date", "retrieved_at",
    "content_hash", "archive_path", "language",
)


class SourceRepository:
    """sources 表读写（文档 8/16.3）。

    source_id 由 (url, content_hash) 派生，与表上 UNIQUE(url, content_hash) 对齐：
    同一 URL 同一内容重复登记幂等；内容变化则新 source_id（新快照）。
    是 documents/evidence/generation_records 外键锚点——采集入库前必须先登记来源。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def derive_id(url: str, content_hash: str | None) -> str:
        import hashlib

        raw = f"{url}::{content_hash or ''}"
        return f"src_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"

    def register(self, source) -> str:
        """登记一条来源，返回 source_id。已存在同 id 则更新元数据（幂等）。"""
        d = source.model_dump()
        row = tuple(_enum_value(d.get(c)) for c in _SOURCE_COLUMNS)
        self.conn.execute(
            _upsert_sql("sources", _SOURCE_COLUMNS, "source_id"), row
        )
        return d["source_id"]

    def get(self, source_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])


_EVIDENCE_COLUMNS = (
    "evidence_id", "source_id", "document_id", "content_hash", "fact_type",
    "fact_key", "source_url", "final_url", "page_number", "table_reference",
    "section_title", "snippet", "locator", "confidence", "parser_version",
    "extraction_version", "task_id", "created_at",
)


class EvidenceRepository:
    """evidence 表读写（文档 14）。

    幂等键为 evidence_id（fact + content_hash 派生）：同一事实同一来源资料
    重复保存不重复入库、不覆盖，保证证据与原始资料不可脱钩。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_if_absent(self, ev) -> bool:
        """保存一条证据。已存在同 evidence_id 则跳过，返回 False。"""
        d = ev.model_dump()
        if not d.get("created_at"):
            d["created_at"] = now_iso()
        row = tuple(_enum_value(d.get(c)) for c in _EVIDENCE_COLUMNS)
        placeholders = ", ".join("?" for _ in _EVIDENCE_COLUMNS)
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO evidence ({', '.join(_EVIDENCE_COLUMNS)}) "
            f"VALUES ({placeholders})",
            row,
        )
        return cur.rowcount > 0

    def get(self, evidence_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()

    def for_fact(self, fact_type: str, fact_key: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM evidence WHERE fact_type = ? AND fact_key = ?",
            (fact_type, fact_key),
        ).fetchall()

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])


class ReviewTransitionError(RuntimeError):
    """Raised when a review decision is not a legal open-item transition."""


class ReviewRepository:
    """review_items 表读写（文档 15）。

    幂等键为 (entity_id, fact_type, fact_key)：同一事实只排一条复核项，
    重复入队更新原因/载荷而不新建。决策 approve/reject/request_more_evidence。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def enqueue(
        self,
        *,
        review_id: str,
        candidate_id: str | None = None,
        entity_id: str,
        fact_type: str,
        fact_key: str,
        reason: str,
        payload: str | None = None,
        task_id: str | None = None,
    ) -> bool:
        """入队一条复核项。已存在同事实键则更新原因/载荷，返回是否新建。"""
        cur = self.conn.execute(
            "INSERT INTO review_items "
            "(review_id, candidate_id, entity_id, fact_type, fact_key, reason, status, payload, "
            " created_at, task_id) "
            "VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?) "
            "ON CONFLICT(entity_id, fact_type, fact_key) DO UPDATE SET "
            "  candidate_id=excluded.candidate_id, reason=excluded.reason, payload=excluded.payload, "
            "  task_id=COALESCE(review_items.task_id, excluded.task_id)",
            (
                review_id, candidate_id, entity_id, fact_type, fact_key, reason, payload,
                now_iso(), task_id,
            ),
        )
        return cur.rowcount > 0 and self._is_new(review_id)

    def _is_new(self, review_id: str) -> bool:
        row = self.conn.execute(
            "SELECT review_id FROM review_items WHERE review_id = ?", (review_id,)
        ).fetchone()
        return row is not None

    def get(self, review_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM review_items WHERE review_id = ?", (review_id,)
        ).fetchone()

    def get_by_fact(
        self, entity_id: str, fact_type: str, fact_key: str
    ) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM review_items "
            "WHERE entity_id = ? AND fact_type = ? AND fact_key = ?",
            (entity_id, fact_type, fact_key),
        ).fetchone()

    def open_items(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM review_items WHERE status = 'open' ORDER BY created_at ASC"
        ).fetchall()

    def resolve(
        self,
        review_id: str,
        *,
        decision: str,
        reviewer: str | None = None,
        resolved_value: str | None = None,
    ) -> None:
        """Record one legal decision from ``open`` using compare-and-set."""
        allowed = {"approve", "reject", "request_more_evidence"}
        if decision not in allowed:
            raise ReviewTransitionError(f"未知复核决策: {decision}")
        row = self.get(review_id)
        if row is None:
            raise ReviewTransitionError(f"复核项不存在: {review_id}")
        if row["status"] != "open":
            raise ReviewTransitionError(
                f"非法复核状态转换: {row['status']} -> {decision}"
            )
        cursor = self.conn.execute(
            "UPDATE review_items SET status = ?, reviewer = ?, resolved_value = ?, "
            "resolved_at = ? WHERE review_id = ? AND status = 'open'",
            (decision, reviewer, resolved_value, now_iso(), review_id),
        )
        if cursor.rowcount != 1:
            raise ReviewTransitionError(f"复核项状态已被并发修改: {review_id}")

    def count(self, *, status: str | None = None) -> int:
        if status is None:
            return int(
                self.conn.execute("SELECT COUNT(*) FROM review_items").fetchone()[0]
            )
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM review_items WHERE status = ?", (status,)
            ).fetchone()[0]
        )


_TASK_RUN_COLUMNS = (
    "task_id", "attempt", "status", "failure_stage", "message",
    "started_at", "finished_at",
)


class TaskRunRepository:
    """task_runs 表读写（任务执行审计）。

    每次任务执行都创建一条 task_run 记录，记录：
    - 第几次尝试（attempt）
    - 执行状态（success/failed）
    - 失败阶段（如果失败）
    - 开始和结束时间
    - 执行消息

    用于追踪任务执行历史和故障排查。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_run(
        self,
        task_id: str,
        attempt: int,
        started_at: str | None = None,
    ) -> int:
        """创建任务执行记录，返回 run_id。"""
        if started_at is None:
            started_at = now_iso()

        cursor = self.conn.execute(
            "INSERT INTO task_runs (task_id, attempt, status, started_at) "
            "VALUES (?, ?, ?, ?)",
            (task_id, attempt, "running", started_at),
        )
        return cursor.lastrowid

    def update_run_success(
        self,
        run_id: int,
        finished_at: str | None = None,
        message: str | None = None,
    ) -> None:
        """标记运行成功。"""
        if finished_at is None:
            finished_at = now_iso()

        self.conn.execute(
            "UPDATE task_runs SET status = ?, finished_at = ?, message = ? "
            "WHERE run_id = ?",
            ("success", finished_at, message, run_id),
        )

    def update_run_failure(
        self,
        run_id: int,
        failure_stage: str,
        message: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        """标记运行失败，记录失败阶段。"""
        if finished_at is None:
            finished_at = now_iso()

        self.conn.execute(
            "UPDATE task_runs SET status = ?, failure_stage = ?, message = ?, "
            "finished_at = ? WHERE run_id = ?",
            ("failed", failure_stage, message, finished_at, run_id),
        )

    def get_runs_for_task(self, task_id: str) -> list[sqlite3.Row]:
        """获取某任务的所有执行记录，按尝试次数倒序。"""
        return self.conn.execute(
            "SELECT * FROM task_runs WHERE task_id = ? ORDER BY attempt DESC",
            (task_id,),
        ).fetchall()

    def get_latest_run(self, task_id: str) -> sqlite3.Row | None:
        """获取某任务的最新执行记录。"""
        return self.conn.execute(
            "SELECT * FROM task_runs WHERE task_id = ? ORDER BY attempt DESC LIMIT 1",
            (task_id,),
        ).fetchone()

    def count(self) -> int:
        """统计总执行次数。"""
        return int(
            self.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]
        )

    def count_by_status(self, status: str) -> int:
        """按状态统计执行次数。"""
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM task_runs WHERE status = ?", (status,)
            ).fetchone()[0]
        )
