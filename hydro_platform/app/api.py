"""API：GUI 调用的后端接口，封装 pipeline orchestrator。

将旧桌面应用的 API 模式移植到新架构：
- 处理单个任务（上传文件、添加 URL）
- 调用 pipeline orchestrator
- 通过桥接层转换错误
- 返回结构化结果供 GUI 显示
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional, Dict, Any

from hydro_platform.acquisition.router import AcquisitionRouter
from hydro_platform.acquisition.http_client import HttpClient
from hydro_platform.archive.archiver import Archiver, ArchiveError
from hydro_platform.parsing.dispatcher import parse_document
from hydro_platform.extraction.rule_extractors import extract_candidates
from hydro_platform.common.enums import ContentKind, AccessMethod
from hydro_platform.acquisition.result import FetchResult, DownloadMeta
from hydro_platform.config.paths import get_user_data_dir, get_database_path
from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import CURRENT_VERSION, migrate
from hydro_platform.app.bridge import (
    BridgeError,
    wrap_acquisition_error,
    wrap_archive_error,
    wrap_parse_error,
    wrap_extraction_error,
    format_error_for_ui,
)


class Api:
    """桌面应用 API：提供单任务处理接口。"""

    _migration_locks: dict[str, threading.RLock] = {}
    _migration_locks_guard = threading.Lock()

    def __init__(self, data_mode: str = "production"):
        """初始化 API。test 模式使用独立数据库和文件目录，不接触正式数据。"""
        if data_mode not in {"production", "test"}:
            raise ValueError("data_mode must be production or test")
        self.data_mode = data_mode
        self.db_path = get_database_path(data_mode)
        self.raw_root = get_user_data_dir(data_mode) / "raw"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_root.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> dict:
        """确保当前数据空间已建表；不会复制或修改另一数据空间。"""
        with self._migration_lock():
            conn = connect(self.db_path)
            try:
                version = migrate(conn)
                return {"data_mode": self.data_mode, "db_path": str(self.db_path), "schema_version": version}
            finally:
                conn.close()

    def reset_test_data(self) -> dict:
        """清空测试数据空间；生产 API 禁止调用。"""
        if self.data_mode != "test":
            raise PermissionError("只能在 test 数据空间清空数据")
        if self.db_path.exists():
            self.db_path.unlink()
        self.raw_root.parent.mkdir(parents=True, exist_ok=True)
        return self.initialize()

    @classmethod
    def _lock_for_path(cls, db_path: Path) -> threading.RLock:
        key = str(db_path.resolve())
        with cls._migration_locks_guard:
            return cls._migration_locks.setdefault(key, threading.RLock())

    def _migration_lock(self) -> threading.RLock:
        return self._lock_for_path(self.db_path)

    def get_db_connection(
        self,
        *,
        migrate_schema: bool = True,
        read_only: bool = False,
    ) -> sqlite3.Connection:
        """获取数据库连接，供 Archiver 和其他组件使用。

        写入路径默认保持历史行为并确保迁移；查询路径应传
        ``migrate_schema=False, read_only=True``，这样已有正式库的历史外键
        孤儿不会在每个页面请求中重复触发迁移或争抢写锁。
        """
        conn = connect(self.db_path, read_only=read_only)
        try:
            if migrate_schema and not read_only:
                with self._migration_lock():
                    migrate(conn)
            return conn
        except Exception:
            # 迁移失败时必须关闭连接；否则下一次前端重试会继承残留连接，
            # 把结构校验错误放大成 database is locked。
            conn.close()
            raise

    @staticmethod
    def _build_acquisition_router() -> AcquisitionRouter:
        """构造 HTTP 优先、Playwright 可用时自动回退的采集路由。

        Playwright 是可选依赖；缺失时工厂返回 ``None``，路由会诚实地报告 HTTP
        失败而不是伪造浏览器成功。安装后无需改业务代码即可启用。
        """
        from hydro_platform.acquisition.browser_client import create_browser_client

        return AcquisitionRouter(
            http_client=HttpClient(),
            browser_client=create_browser_client(),
        )

    # ==================== 只读产品 API（第一阶段：让程序有内容）====================
    # 前端通过 pywebview.api.<method> 调用；每个方法自开自关连接，线程安全。

    def _read(self, fn):
        """以只读查询层执行 fn(queries)，自动管理连接。"""
        from hydro_platform.app.queries import ReadQueries
        conn = self.get_db_connection(migrate_schema=False, read_only=True)
        try:
            return fn(ReadQueries(conn))
        finally:
            conn.close()

    def get_dashboard(self) -> Dict[str, Any]:
        """工作台首页聚合数据（基线第 8 节）。"""
        return self._read(lambda q: q.get_dashboard())

    def list_stations(
        self,
        search: Optional[str] = None,
        country: Optional[str] = None,
        status: Optional[str] = None,
        min_capacity: Optional[float] = None,
        max_capacity: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """水电站列表（基线第 9 节）。"""
        return self._read(
            lambda q: q.list_stations(
                search=search,
                country=country,
                status=status,
                min_capacity=min_capacity,
                max_capacity=max_capacity,
                limit=limit,
                offset=offset,
            )
        )

    def list_countries(self) -> Any:
        """筛选下拉用的国家列表。"""
        return self._read(lambda q: q.list_countries())

    def get_station_detail(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """水电站详情（基线第 10 节）。"""
        return self._read(lambda q: q.get_station_detail(entity_id))

    def get_station_generation(self, entity_id: str) -> Any:
        """某电站年度发电量（基线 10.2）。"""
        return self._read(lambda q: q.get_station_generation(entity_id))

    def get_all_stations(self) -> Dict[str, Any]:
        """获取所有电站列表（用于前端电站选择器）。"""
        def query(q):
            conn = q.conn
            rows = conn.execute("""
                SELECT entity_id, canonical_name, local_name, country, capacity_mw
                FROM stations
                ORDER BY
                    CASE
                        WHEN country = 'CN' THEN 1
                        WHEN country = 'US' THEN 2
                        ELSE 3
                    END,
                    capacity_mw DESC NULLS LAST,
                    canonical_name
            """).fetchall()
            return {
                "stations": [
                    {
                        "entity_id": r["entity_id"],
                        "name_zh": r["local_name"] or r["canonical_name"],
                        "name_en": r["canonical_name"],
                        "country": r["country"],
                        "capacity_mw": r["capacity_mw"]
                    }
                    for r in rows
                ]
            }
        return self._read(query)

    def list_data_gaps(self, limit: int = 50, offset: int = 0) -> Any:
        """数据缺口列表（基线第 12 节）。"""
        return self._read(lambda q: q.list_data_gaps(limit=limit, offset=offset))

    def detect_data_gaps(self, limit: int = 100) -> Any:
        """智能检测数据缺口：哪些高优先级电站缺少哪些年份的数据。"""
        return self._read(lambda q: q.detect_data_gaps(limit=limit))

    def get_data_coverage_stats(self) -> Any:
        """数据覆盖率统计：按国家、年份的覆盖情况。"""
        return self._read(lambda q: q.get_data_coverage_stats())

    def browse_records(
        self,
        entity_id: Optional[str] = None,
        year: Optional[str] = None,
        value_type: Optional[str] = None,
        published_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """数据浏览（基线 18.1）。"""
        return self._read(
            lambda q: q.browse_records(
                entity_id=entity_id,
                year=year,
                value_type=value_type,
                published_only=published_only,
                limit=limit,
                offset=offset,
            )
        )

    def get_top100(self, year: Optional[str] = None) -> Any:
        """Top 100（基线 18.2）。"""
        return self._read(lambda q: q.get_top100(year))

    # ==================== 复核中心 API（第二阶段）====================

    def list_review_items(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """待复核记录列表。"""
        return self._read(lambda q: q.list_review_items(status, limit, offset))

    def get_review_detail(self, record_id: int | str) -> Optional[Dict[str, Any]]:
        """按 review_id 获取复核详情；兼容旧 generation_records.id。"""
        return self._read(lambda q: q.get_review_detail(record_id))

    def _review_item_for_record(self, conn, record_id: int | str):
        """解析新的 review_id 主键，并兼容旧 generation_records.id。"""
        import json
        review = conn.execute(
            "SELECT * FROM review_items WHERE review_id = ?", (str(record_id),)
        ).fetchone()
        if review is not None:
            record = None
            if review["candidate_id"]:
                record = conn.execute(
                    "SELECT * FROM generation_records WHERE candidate_id = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (review["candidate_id"],),
                ).fetchone()
            return record, review

        record = conn.execute("SELECT * FROM generation_records WHERE id = ?", (record_id,)).fetchone()
        if record is None:
            return None, None
        rows = conn.execute(
            "SELECT * FROM review_items WHERE entity_id = ? AND fact_type = 'generation' AND status = 'open'",
            (record['entity_id'],),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row['payload'] or '{}')
                cand = payload.get('candidate', {})
                if (str(cand.get('period_label')) == str(record['period_label'])
                        and cand.get('value_type', 'actual') == record['value_type']
                        and cand.get('measurement_scope', 'plant') == record['measurement_scope']):
                    return record, row
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return record, None

    def _ensure_review_task(self, conn, review, candidate=None, record=None):
        """确保复核决策关联的是一个已持久化、可决策的任务。

        早期 CSV 导入只创建了 candidate/review/evidence，遗漏了 ``tasks``
        中的父任务；而 ``task_runs.task_id`` 是强外键。这里在同一连接中
        为该类历史复核项补建一个稳定的人工任务，并把可关联的记录补上
        task_id。新 CSV 导入也复用这套契约，避免两条路径各自造任务。
        """
        import hashlib

        from hydro_platform.common.enums import EntityType, TaskStatus, TaskType
        from hydro_platform.database.repositories import TaskRepository
        from hydro_platform.models.task import Task
        from hydro_platform.tasking.manager import TaskManager

        linked_task_id = review["task_id"] or (
            candidate["task_id"] if candidate is not None else None
        )
        if linked_task_id:
            task_repo = TaskRepository(conn)
            existing = task_repo.get(str(linked_task_id))
            if existing is not None:
                if review["status"] == "open":
                    TaskManager(conn).reopen_failed_for_open_review(str(linked_task_id))
                    existing = task_repo.get(str(linked_task_id))
                return Task.model_validate(dict(existing))

        entity_id = (
            candidate["entity_id"] if candidate is not None else record["entity_id"]
            if record is not None else review["entity_id"]
        )
        period_label = (
            candidate["period_label"] if candidate is not None else record["period_label"]
            if record is not None else None
        )
        stable_key = str(
            candidate["candidate_id"] if candidate is not None else review["review_id"]
        )
        digest = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]
        task_id = str(linked_task_id or f"manual_review::{digest}")
        target_period = f"{period_label or '-'}::review::{digest}"
        task = Task(
            task_id=task_id,
            entity_id=entity_id,
            entity_type=EntityType.STATION,
            # USER_QUERY 明确表示用户主动提交的 CSV/历史人工复核工作，
            # 不与自动采集的 (entity, station_generation, year) 任务冲突。
            task_type=TaskType.USER_QUERY,
            target_period=target_period,
            status=TaskStatus.NEEDS_REVIEW,
            source_type="manual",
            user_specified_source=f"review://{review['review_id']}",
        )
        TaskRepository(conn).upsert_many([task])

        # 历史行允许 task_id 为 NULL。只补空值，绝不覆盖已建立的有效溯源。
        conn.execute(
            "UPDATE review_items SET task_id = ? WHERE review_id = ? AND task_id IS NULL",
            (task.task_id, review["review_id"]),
        )
        if candidate is not None:
            conn.execute(
                "UPDATE extraction_candidates SET task_id = ? "
                "WHERE candidate_id = ? AND task_id IS NULL",
                (task.task_id, candidate["candidate_id"]),
            )
            conn.execute(
                "UPDATE evidence SET task_id = ? WHERE evidence_id IN ("
                "SELECT evidence_id FROM candidate_evidence WHERE candidate_id = ?"
                ") AND task_id IS NULL",
                (task.task_id, candidate["candidate_id"]),
            )
        if record is not None:
            conn.execute(
                "UPDATE generation_records SET task_id = ? WHERE id = ? AND task_id IS NULL",
                (task.task_id, record["id"]),
            )
        return task

    def approve_record(self, record_id: int | str) -> Dict[str, Any]:
        """【已改造】通过 orchestrator 正式复核并发布。

        Args:
            record_id: 记录 ID

        Returns:
            {
                "status": "success" | "failed",
                "record_id": int,
                "review_id": str | None,
                "message": str
            }
        """
        from hydro_platform.pipeline.orchestrator import apply_review_decision
        from hydro_platform.pipeline.context import PipelineContext
        from hydro_platform.acquisition.router import AcquisitionRouter
        from hydro_platform.acquisition.http_client import HttpClient

        conn = self.get_db_connection()
        try:
            record, review = self._review_item_for_record(conn, record_id)
            if review is None:
                return {"status": "failed", "record_id": record_id, "message": "复核项不存在"}

            candidate = None
            if review["candidate_id"]:
                candidate = conn.execute(
                    "SELECT * FROM extraction_candidates WHERE candidate_id = ?",
                    (review["candidate_id"],),
                ).fetchone()
            evidence_ok = bool(record is not None and record["evidence_id"])
            if candidate is not None:
                evidence_ok = evidence_ok or conn.execute(
                    """
                    SELECT 1 FROM candidate_evidence ce
                    JOIN evidence e ON e.evidence_id = ce.evidence_id
                    WHERE ce.candidate_id = ? LIMIT 1
                    """,
                    (candidate["candidate_id"],),
                ).fetchone() is not None
            if not evidence_ok:
                return {"status": "failed", "record_id": record_id, "message": "缺少证据，不能发布"}

            if candidate is None and record is None:
                return {"status": "failed", "record_id": record_id, "message": "候选内容不存在"}

            task = self._ensure_review_task(conn, review, candidate, record)

            # 构造 Pipeline 上下文（仅用于复核决策）
            ctx = PipelineContext(
                conn=conn,
                router=AcquisitionRouter(http_client=HttpClient()),
                url_resolver=None,  # 复核不需要采集
                raw_root=self.raw_root,
                reviewer="desktop_app"
            )

            # 调用 orchestrator 执行 approve
            result = apply_review_decision(ctx, task, review['review_id'], 'approve')

            # apply_review_decision 会调用多个仓储层；在 API 边界提交最后的
            # task_run 状态，避免成功审核后运行记录仍停在 running。
            conn.commit()

            if result.succeeded:
                return {
                    "status": "success",
                    "record_id": record_id,
                    "review_id": review['review_id'],
                    "message": "已通过复核并发布"
                }
            else:
                return {
                    "status": "failed",
                    "record_id": record_id,
                    "review_id": review['review_id'],
                    "message": result.error or "复核失败"
                }
        finally:
            conn.close()

    def reject_record(self, record_id: int | str, reason: str) -> Dict[str, Any]:
        """【已改造】通过 orchestrator 正式复核拒绝。

        Args:
            record_id: 记录 ID
            reason: 拒绝原因

        Returns:
            {
                "status": "success" | "failed",
                "record_id": int,
                "review_id": str | None,
                "message": str
            }
        """
        from hydro_platform.pipeline.orchestrator import apply_review_decision
        from hydro_platform.pipeline.context import PipelineContext
        from hydro_platform.acquisition.router import AcquisitionRouter
        from hydro_platform.acquisition.http_client import HttpClient

        conn = self.get_db_connection()
        try:
            record, review = self._review_item_for_record(conn, record_id)
            if review is None:
                return {"status": "failed", "record_id": record_id, "message": "复核项不存在"}

            candidate = None
            if review["candidate_id"]:
                candidate = conn.execute(
                    "SELECT * FROM extraction_candidates WHERE candidate_id = ?",
                    (review["candidate_id"],),
                ).fetchone()
            if candidate is None and record is None:
                return {"status": "failed", "record_id": record_id, "message": "候选内容不存在"}

            task = self._ensure_review_task(conn, review, candidate, record)

            # 构造 Pipeline 上下文
            ctx = PipelineContext(
                conn=conn,
                router=AcquisitionRouter(http_client=HttpClient()),
                url_resolver=None,
                raw_root=self.raw_root,
                reviewer="desktop_app"
            )

            # 调用 orchestrator 执行 reject
            result = apply_review_decision(ctx, task, review['review_id'], 'reject', reason)
            conn.commit()

            # 驳回是一个成功执行的复核决策，但其任务终态按业务定义为 failed。
            # 不能用 PipelineResult.succeeded（只代表任务 success）判断 API 成功。
            from hydro_platform.common.enums import FailureStage
            if result.failure_stage == FailureStage.REVIEW_REJECTED and not result.error:
                return {
                    "status": "success",
                    "record_id": record_id,
                    "review_id": review['review_id'],
                    "message": f"已拒绝：{reason}"
                }
            else:
                return {
                    "status": "failed",
                    "record_id": record_id,
                    "review_id": review['review_id'],
                    "message": result.error or "复核驳回失败"
                }
        finally:
            conn.close()

    def cancel_review(self, record_id: int, reason: str = None) -> Dict[str, Any]:
        """D11：取消复核，状态回滚。

        Args:
            record_id: 记录 ID
            reason: 取消原因（可选）

        Returns:
            {
                "status": "success" | "failed",
                "record_id": int,
                "review_id": str | None,
                "message": str
            }
        """
        from hydro_platform.pipeline.orchestrator import cancel_review
        from hydro_platform.pipeline.context import PipelineContext
        from hydro_platform.acquisition.router import AcquisitionRouter
        from hydro_platform.acquisition.http_client import HttpClient

        conn = self.get_db_connection()
        try:
            record, review = self._review_item_for_record(conn, record_id)
            if record is None:
                return {"status": "failed", "record_id": record_id, "message": "记录不存在"}
            if review is None:
                return {"status": "failed", "record_id": record_id, "message": "没有对应的待复核项"}

            # 构造 Pipeline 上下文
            ctx = PipelineContext(
                conn=conn,
                router=AcquisitionRouter(http_client=HttpClient()),
                url_resolver=None,
                raw_root=self.raw_root,
                reviewer="desktop_app"
            )

            # 调用 orchestrator 执行 cancel
            result = cancel_review(ctx, review['review_id'], reason)

            if result.succeeded:
                return {
                    "status": "success",
                    "record_id": record_id,
                    "review_id": review['review_id'],
                    "message": f"已取消复核" + (f"：{reason}" if reason else "")
                }
            else:
                return {
                    "status": "failed",
                    "record_id": record_id,
                    "review_id": review['review_id'],
                    "message": result.error or "取消复核失败"
                }
        finally:
            conn.close()

    def batch_approve(self, record_ids: list) -> Dict[str, Any]:
        """批量批准复核项。"""
        success_count = 0
        failed_count = 0
        errors = []

        for record_id in record_ids:
            try:
                result = self.approve_record(record_id)
                if result.get('status') == 'success':
                    success_count += 1
                else:
                    failed_count += 1
                    errors.append(f"记录{record_id}: {result.get('message', '未知错误')}")
            except Exception as e:
                failed_count += 1
                errors.append(f"记录{record_id}: {str(e)}")

        return {
            "status": "success",
            "success": success_count,
            "failed": failed_count,
            "total": len(record_ids),
            "errors": errors
        }

    def batch_reject(self, record_ids: list, reason: str) -> Dict[str, Any]:
        """批量驳回复核项。"""
        success_count = 0
        failed_count = 0
        errors = []

        for record_id in record_ids:
            try:
                result = self.reject_record(record_id, reason)
                if result.get('status') == 'success':
                    success_count += 1
                else:
                    failed_count += 1
                    errors.append(f"记录{record_id}: {result.get('message', '未知错误')}")
            except Exception as e:
                failed_count += 1
                errors.append(f"记录{record_id}: {str(e)}")

        return {
            "status": "success",
            "success": success_count,
            "failed": failed_count,
            "total": len(record_ids),
            "errors": errors
        }

    # ==================== 来源管理 API ====================

    def list_sources(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """来源列表。"""
        return self._read(lambda q: q.list_sources(limit, offset))

    # ==================== 文档资料 API ====================

    def list_documents(
        self,
        source_id: Optional[str] = None,
        content_kind: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """文档列表。"""
        return self._read(lambda q: q.list_documents(source_id, content_kind, limit, offset))

    # ==================== 证据中心 API ====================

    def list_evidence(
        self,
        document_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """证据列表。"""
        return self._read(lambda q: q.list_evidence(document_id, limit, offset))

    # ==================== 项目管理 API ====================

    def list_projects(
        self,
        search: Optional[str] = None,
        country: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """项目列表。"""
        return self._read(lambda q: q.list_projects(
            search=search, country=country, status=status, limit=limit, offset=offset
        ))

    # ==================== 任务管理 API ====================

    @staticmethod
    def _intelligent_station_matches(conn, station_name: str) -> list[dict[str, Any]]:
        """严格匹配 seedlist 名称、当地名称或别名；歧义时绝不猜测。"""
        needle = " ".join(station_name.casefold().split())
        rows = conn.execute(
            """SELECT entity_id, canonical_name, local_name, aliases, country, operator, owner,
                      gem_wiki_url FROM stations"""
        ).fetchall()
        matches: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            names = [item.get("canonical_name"), item.get("local_name")]
            aliases = str(item.get("aliases") or "").replace("；", ";").replace("|", ";")
            names.extend(part.strip() for part in aliases.split(";") if part.strip())
            if any(" ".join(str(name).casefold().split()) == needle for name in names if name):
                matches.append(item)
        # 模型偶尔省略地理前缀（如“金沙江乌东德水电站”→“乌东德水电站”）。
        # 仅在严格匹配为空且该简称唯一时允许返回；多条则仍要求用户澄清。
        if not matches and len(needle) >= 4:
            for row in rows:
                item = dict(row)
                names = [item.get("canonical_name"), item.get("local_name")]
                aliases = str(item.get("aliases") or "").replace("；", ";").replace("|", ";")
                names.extend(part.strip() for part in aliases.split(";") if part.strip())
                if any(needle in " ".join(str(name).casefold().split()) for name in names if name):
                    matches.append(item)
        return matches

    @staticmethod
    def _write_intelligent_event(conn, plan_id: str, stage: str, message: str, payload: Optional[dict] = None) -> None:
        """记录不含密钥的智能任务审计事件。"""
        import json
        import uuid
        from hydro_platform.common.clock import now_iso

        conn.execute(
            """INSERT INTO intelligent_task_events
               (event_id, plan_id, stage, message, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f"agent_evt_{uuid.uuid4().hex[:16]}", plan_id, stage, message,
             json.dumps(payload, ensure_ascii=False) if payload else None, now_iso()),
        )

    @staticmethod
    def _station_search_intent(station: dict, target_period: str):
        """为详情页和自然语言任务生成同一份、可审计的来源发现意图。"""
        import re

        from hydro_platform.intelligence.deepseek_agent import TaskIntent

        name = str(station.get("local_name") or station.get("canonical_name") or "").strip()
        canonical = str(station.get("canonical_name") or name).strip()
        # GEM 的当地名称常带河流前缀和“水电站”全称，但发布公告时通常写成
        # “三峡电站”这类短名。这里的变体是确定性规则，不依赖模型翻译。
        search_name = re.sub(r"^(?:长江|金沙江|雅砻江|澜沧江|黄河|珠江|红水河)", "", name)
        search_name = re.sub(r"水电(?:站|厂)$", "电站", search_name)
        is_chinese = bool(re.search(r"[\u4e00-\u9fff]", search_name))
        if is_chinese:
            queries = [
                # 国内搜索引擎对带英文引号的中文短名会明显改变排序；这里使用
                # 自然词组，才能优先命中“完成发电量”类公开公告。
                f'{search_name} {target_period} 完成发电量',
                f'{search_name} {target_period} 发电量 年度报告',
                f'"{canonical}" {target_period} annual generation annual report',
            ]
        else:
            queries = [
                f'"{name}" {target_period} annual generation',
                f'"{canonical}" {target_period} annual generation annual report',
            ]
            operator = str(station.get("operator") or station.get("owner") or "").strip()
            if operator:
                queries.append(f'"{operator}" {target_period} annual report "{name}" generation')
        return TaskIntent(
            station_name=name, target_period=str(target_period), metric="generation",
            source_policy="official_or_authority", query_hints=tuple(queries[:3]),
        )

    @staticmethod
    def _gem_external_candidates(conn, station: dict, intent) -> list[dict]:
        """仅把 GEM 外链作为统一发现引擎的一个补充通道。"""
        from hydro_platform.discovery.official import OfficialSourceFinder

        if not station.get("gem_wiki_url"):
            return []
        task = {
            "entity_id": station["entity_id"], "entity_name": station["canonical_name"],
            "country": station.get("country"), "target_period": intent.target_period,
            "metric": intent.metric,
        }
        try:
            values = OfficialSourceFinder(conn).find(task)
        except Exception:
            # GEM 只是补充线索；它不可用不能阻断真实搜索通道。
            return []
        return [item.to_dict() for item in values if item.discovery_method == "gem_wiki_external_link"]

    def _discover_trusted_source_candidates(self, conn, *, station: dict, intent, agent, on_event=None) -> tuple[list[dict], list[dict], list[str], int]:
        """唯一的可信来源发现入口；只写候选台账，绝不创建采集任务。"""
        from hydro_platform.discovery.ledger import SourceDiscoveryLedger
        from hydro_platform.intelligence.trusted_source_discovery import TrustedSourceDiscovery

        gem_candidates = self._gem_external_candidates(conn, station, intent)
        engine = TrustedSourceDiscovery(agent=agent)

        def emit(stage: str, payload: dict) -> None:
            if on_event:
                on_event(stage, payload)

        qualified, audited, warnings = engine.discover(
            intent=intent, station=station, gem_candidates=gem_candidates, on_event=emit,
        )
        if intent.source_policy == "official_only":
            for item in qualified:
                if item.get("source_type") != "official":
                    item["status"] = "ineligible"
                    item["error"] = "用户要求仅官方来源"
            qualified = [item for item in qualified if item.get("source_type") == "official"]
        stored = SourceDiscoveryLedger(conn).record_candidates(
            entity_id=station["entity_id"], gem_wiki_url=station.get("gem_wiki_url"), candidates=audited,
        )
        stored_by_url = {
            item.get("canonical_url") or item.get("url"): item
            for item in stored
        }
        # 被人工拒绝的候选不应在下一次发现时重新作为“推荐来源”出现。
        items = []
        for item in qualified:
            saved = stored_by_url.get(item.get("canonical_url") or item.get("url"), item)
            if saved.get("status") != "rejected":
                items.append(saved)
        # 严格合格项与“已发现、但不能自动处理”的线索必须分开。后者过去
        # 被界面吞掉，造成用户误以为程序没有执行检索。
        qualified_urls = {item.get("canonical_url") or item.get("url") for item in items}
        review_items = [
            item for item in stored
            if (item.get("canonical_url") or item.get("url")) not in qualified_urls
            and item.get("status") != "rejected"
            and item.get("access_status") in {"reachable", "requires_browser"}
        ][:8]
        return items, review_items, warnings, len(stored)

    def create_intelligent_task(self, prompt: str, auto_execute: bool = False) -> Dict[str, Any]:
        """由一句自然语言创建“规划任务”，并自动完成 DeepSeek 联网候选发现。

        规划任务与正式采集任务严格分离：本方法不会下载资料、不会创建 ``sources``，
        也不会写事实数据。用户在候选中明确选择后，才可创建普通采集任务。
        """
        import json
        import uuid

        from hydro_platform.common.clock import now_iso
        from hydro_platform.config.llm_config import LLMConfig
        from hydro_platform.intelligence.deepseek_agent import DeepSeekAgentError, DeepSeekResponsesAgent

        prompt = (prompt or "").strip()
        if not prompt:
            return {"success": False, "error": "请输入自然语言任务", "items": []}
        if len(prompt) > 2000:
            return {"success": False, "error": "任务描述不能超过 2000 个字符", "items": []}

        deepseek = LLMConfig().get_deepseek_config()
        if not deepseek or not deepseek.get("api_key"):
            return {"success": False, "error": "未配置 DeepSeek API Key，请先在设置中配置并测试连接", "items": []}
        # 联网搜索与任务理解沿用用户明确配置的 DeepSeek 模型；统一发现服务会
        # 同时调用 DeepSeek 原生搜索和程序控制的搜索，任一通道故障可降级。
        agent_model = deepseek.get("model") or "deepseek-chat"
        agent = DeepSeekResponsesAgent(api_key=deepseek["api_key"], model=agent_model)
        plan_id = f"agent_{uuid.uuid4().hex[:16]}"
        now = now_iso()
        conn = self.get_db_connection()
        try:
            conn.execute(
                """INSERT INTO intelligent_task_plans
                   (plan_id, user_prompt, auto_execute, status, created_at, updated_at)
                   VALUES (?, ?, ?, 'planning', ?, ?)""",
                (plan_id, prompt, int(bool(auto_execute)), now, now),
            )
            self._write_intelligent_event(conn, plan_id, "planning", "已接收自然语言任务，开始解析意图")
            conn.commit()

            intent = agent.plan(prompt, auto_execute=auto_execute)
            matches = self._intelligent_station_matches(conn, intent.station_name)
            if len(matches) != 1:
                message = "未能唯一匹配 seedlist 电站，请使用电站标准名称或本地名称重新描述任务"
                conn.execute(
                    """UPDATE intelligent_task_plans
                       SET status='needs_input', intent_json=?, error=?, updated_at=? WHERE plan_id=?""",
                    (json.dumps(intent.to_dict(), ensure_ascii=False), message, now_iso(), plan_id),
                )
                self._write_intelligent_event(conn, plan_id, "needs_input", message,
                                              {"station_name": intent.station_name,
                                               "matches": [{"entity_id": item["entity_id"], "canonical_name": item["canonical_name"]} for item in matches[:10]]})
                conn.commit()
                return {"success": True, "plan_id": plan_id, "status": "needs_input", "intent": intent.to_dict(),
                        "station_matches": [{"entity_id": item["entity_id"], "canonical_name": item["canonical_name"]} for item in matches[:10]],
                        "items": [], "message": message}

            station = matches[0]
            self._write_intelligent_event(conn, plan_id, "searching", "已匹配电站，正在融合 DeepSeek、程序搜索与 GEM 外链",
                                          {"entity_id": station["entity_id"], "canonical_name": station["canonical_name"]})
            conn.commit()
            if not intent.query_hints:
                intent = self._station_search_intent(station, intent.target_period)

            def discovery_event(stage: str, payload: dict) -> None:
                labels = {
                    "query_planning": "正在根据电站别名和运营方规划高精度检索词",
                    "query_planning_done": "高精度检索词规划完成",
                    "official_disclosure_search": "正在查询交易所官方披露目录",
                    "official_disclosure_search_done": "交易所官方披露目录查询完成",
                    "deepseek_search": "正在执行 DeepSeek 原生联网搜索",
                    "deepseek_search_done": "DeepSeek 原生联网搜索完成",
                    "program_search": "正在执行程序控制的真实搜索",
                    "program_search_done": "程序控制的真实搜索完成",
                }
                self._write_intelligent_event(conn, plan_id, stage, labels.get(stage, stage), payload)

            usable, review_items, warnings, audited_count = self._discover_trusted_source_candidates(
                conn, station=station, intent=intent, agent=agent, on_event=discovery_event,
            )
            status = "ready" if usable else "no_candidates"
            message = (
                f"已融合 DeepSeek 原生搜索、程序搜索和 GEM 外链，共审计 {audited_count} 个候选，保留 {len(usable)} 个可继续处理的链接。"
                if usable else "已完成多通道搜索，但没有候选同时通过可访问性、年份、电站和年度发电量校验；未创建采集任务。"
            )
            if warnings:
                message += " " + "；".join(warnings)
            conn.execute(
                """UPDATE intelligent_task_plans SET entity_id=?, target_period=?, metric=?, source_policy=?,
                   auto_execute=?, status=?, intent_json=?, search_queries_json=?, candidate_json=?, error=NULL,
                   updated_at=? WHERE plan_id=?""",
                (station["entity_id"], intent.target_period, intent.metric, intent.source_policy, int(intent.auto_execute),
                 status, json.dumps(intent.to_dict(), ensure_ascii=False), json.dumps(list(intent.query_hints), ensure_ascii=False),
                 json.dumps(usable, ensure_ascii=False), now_iso(), plan_id),
            )
            self._write_intelligent_event(conn, plan_id, status, message,
                                          {"audited": audited_count, "usable": len(usable), "warnings": warnings})
            conn.commit()
            return {"success": True, "plan_id": plan_id, "status": status, "llm_model": agent_model, "intent": intent.to_dict(),
                    "station": {"entity_id": station["entity_id"], "canonical_name": station["canonical_name"]},
                    "items": usable, "review_items": review_items, "message": message}
        except DeepSeekAgentError as exc:
            error = str(exc)
        except Exception as exc:
            error = str(exc)
        conn.execute("UPDATE intelligent_task_plans SET status='failed', error=?, updated_at=? WHERE plan_id=?",
                     (error, now_iso(), plan_id))
        self._write_intelligent_event(conn, plan_id, "failed", error)
        conn.commit()
        return {"success": False, "plan_id": plan_id, "error": error, "items": []}
        
    def get_intelligent_task_plan(self, plan_id: str) -> Dict[str, Any]:
        """读取智能任务的可审计计划及事件；绝不返回 LLM 凭据。"""
        import json

        conn = self.get_db_connection()
        try:
            row = conn.execute("SELECT * FROM intelligent_task_plans WHERE plan_id=?", (plan_id,)).fetchone()
            if row is None:
                return {"success": False, "error": "智能任务不存在"}
            plan = dict(row)
            for field in ("intent_json", "search_queries_json", "candidate_json"):
                raw = plan.get(field)
                plan[field[:-5]] = json.loads(raw) if raw else None
                del plan[field]
            events = [dict(item) for item in conn.execute(
                "SELECT stage, message, payload_json, created_at FROM intelligent_task_events WHERE plan_id=? ORDER BY created_at",
                (plan_id,),
            ).fetchall()]
            for event in events:
                event["payload"] = json.loads(event.pop("payload_json")) if event.get("payload_json") else None
            return {"success": True, "plan": plan, "events": events}
        finally:
            conn.close()

    def create_collection_task_from_intelligent_plan(self, plan_id: str, url: str) -> Dict[str, Any]:
        """用户从已验证智能候选中选择一个 URL，才创建正式采集任务。"""
        import json

        conn = self.get_db_connection()
        try:
            row = conn.execute(
                "SELECT entity_id, target_period, status, candidate_json FROM intelligent_task_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if row is None:
                return {"success": False, "error": "智能任务不存在"}
            if row["status"] != "ready":
                return {"success": False, "error": "该智能任务没有可确认的候选来源"}
            candidates = json.loads(row["candidate_json"] or "[]")
            selected = next((item for item in candidates if url in {item.get("url"), item.get("canonical_url"), item.get("final_url")}), None)
            if selected is None or selected.get("access_status") not in {"reachable", "requires_browser"}:
                return {"success": False, "error": "只能从通过访问预检的智能候选中创建采集任务"}
        finally:
            conn.close()

        result = self.create_task(
            row["entity_id"], row["target_period"], "generation_annual",
            source_type="intelligent", user_specified_source=selected.get("final_url") or selected.get("url"),
        )
        if result.get("success"):
            conn = self.get_db_connection()
            try:
                conn.execute("UPDATE intelligent_task_plans SET status='collection_queued', updated_at=datetime('now') WHERE plan_id=?", (plan_id,))
                self._write_intelligent_event(conn, plan_id, "collection_queued", "用户已确认候选，已创建正式采集任务",
                                              {"task_id": result["task_id"], "url": selected.get("final_url") or selected.get("url")})
                conn.commit()
            finally:
                conn.close()
        return result

    def list_tasks(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """采集任务列表。"""
        return self._read(lambda q: q.list_tasks(status=status, limit=limit, offset=offset))

    def cancel_queued_task(self, task_id: str) -> Dict[str, Any]:
        """取消一个未完成任务，保留任务与运行审计记录。"""
        from hydro_platform.tasking.manager import TaskManager, TaskNotFound
        from hydro_platform.tasking.state_machine import IllegalTransition

        conn = self.get_db_connection()
        try:
            manager = TaskManager(conn)
            manager.cancel(str(task_id))
            return {"success": True, "task_id": task_id, "status": "cancelled"}
        except (TaskNotFound, IllegalTransition) as exc:
            return {"success": False, "task_id": task_id, "error": str(exc)}
        except Exception as exc:
            return {"success": False, "task_id": task_id, "error": str(exc)}
        finally:
            conn.close()

    def retry_failed_task(self, task_id: str) -> Dict[str, Any]:
        """将未达到重试上限的失败任务重新排入 pending 队列。"""
        from hydro_platform.tasking.manager import TaskManager, TaskNotFound
        from hydro_platform.tasking.state_machine import IllegalTransition

        conn = self.get_db_connection()
        try:
            manager = TaskManager(conn)
            requeued = manager.requeue(str(task_id))
            if not requeued:
                return {
                    "success": False,
                    "task_id": task_id,
                    "error": "任务已达到最大重试次数，不能重新排队",
                }
            return {"success": True, "task_id": task_id, "status": "pending"}
        except (TaskNotFound, IllegalTransition) as exc:
            return {"success": False, "task_id": task_id, "error": str(exc)}
        except Exception as exc:
            return {"success": False, "task_id": task_id, "error": str(exc)}
        finally:
            conn.close()

    def restart_intelligent_task(self, task_id: str) -> Dict[str, Any]:
        """在用户明确确认后，使用已保存的智能来源重新排队。

        这不是普通失败重试：智能计划已保留用户确认过的 URL。出现因程序版本
        修复或下载器兼容性导致的失败时，允许用户显式重新开始一次新的尝试周期；
        历史 task_runs 保留，不删除审计记录。
        """
        from hydro_platform.tasking.manager import TaskManager, TaskNotFound
        from hydro_platform.tasking.state_machine import IllegalTransition

        conn = self.get_db_connection()
        try:
            row = conn.execute(
                "SELECT status, source_type, user_specified_source FROM tasks WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                raise TaskNotFound(str(task_id))
            if row["status"] != "failed":
                return {"success": False, "task_id": task_id, "error": "只有失败的智能采集任务可以重新开始"}
            if row["source_type"] != "intelligent" or not row["user_specified_source"]:
                return {"success": False, "task_id": task_id, "error": "该任务没有已确认的智能来源"}

            # 仅在用户点击“使用已选来源重试”后重置尝试计数；状态转换仍由
            # TaskManager 统一执行，保留既有运行审计。
            conn.execute("UPDATE tasks SET attempts = 0 WHERE task_id = ?", (str(task_id),))
            requeued = TaskManager(conn).requeue(str(task_id))
            if not requeued:
                return {"success": False, "task_id": task_id, "error": "重新排队失败"}
            return {
                "success": True,
                "task_id": task_id,
                "status": "pending",
                "source_url": row["user_specified_source"],
            }
        except (TaskNotFound, IllegalTransition) as exc:
            return {"success": False, "task_id": task_id, "error": str(exc)}
        except Exception as exc:
            return {"success": False, "task_id": task_id, "error": str(exc)}
        finally:
            conn.close()

    def cancel_test_tasks(self) -> Dict[str, Any]:
        """批量取消 test_ 前缀的非终态任务，不删除历史审计。"""
        from hydro_platform.common.enums import TaskStatus
        from hydro_platform.tasking.manager import TaskManager
        from hydro_platform.models.task import Task

        conn = self.get_db_connection()
        try:
            rows = conn.execute(
                "SELECT task_id, status FROM tasks "
                "WHERE substr(task_id, 1, 5) = 'test_' "
                "OR substr(entity_id, 1, 5) = 'test_'"
            ).fetchall()
            cancellable = [
                row["task_id"] for row in rows
                if row["status"] in {
                    TaskStatus.PENDING.value,
                    TaskStatus.RUNNING.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.NEEDS_REVIEW.value,
                }
            ]
            cancelled = TaskManager(conn).cancel_many(cancellable)
            return {
                "success": True,
                "cancelled_count": len(cancelled),
                "cancelled_task_ids": cancelled,
                "skipped_count": len(rows) - len(cancelled),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        finally:
            conn.close()

    def global_search(self, query: str) -> Dict[str, Any]:
        """全局搜索：水电站、项目、来源。"""
        return self._read(lambda q: q.global_search(query))

    # ==================== 设置 API ====================

    def get_system_info(self) -> Dict[str, Any]:
        """系统信息。"""
        return self._read(lambda q: q.get_system_info())

    def get_data_space_info(self) -> Dict[str, Any]:
        """只读返回数据空间状态，不在页面查询期间隐式执行迁移。

        已有正式库如果包含历史外键孤儿，迁移必须停在数据负责人决定处置
        之前；测试/设置页面仍应能显示路径、版本和待治理数量。
        """
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return self.initialize()

        conn = self.get_db_connection(migrate_schema=False, read_only=True)
        try:
            try:
                row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
                version = int(row[0] or 0)
            except sqlite3.OperationalError:
                version = 0
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            return {
                "data_mode": self.data_mode,
                "db_path": str(self.db_path),
                "schema_version": version,
                "target_schema_version": CURRENT_VERSION,
                "migration_required": version < CURRENT_VERSION,
                "foreign_key_violations": len(violations),
                "read_only_compatible": True,
            }
        finally:
            conn.close()

    def export_database(self) -> Dict[str, Any]:
        """导出数据库到用户指定位置。"""
        import shutil
        from datetime import datetime

        # 生成导出文件名（带时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_filename = f"hydropower_export_{timestamp}.db"

        # 导出到数据目录的 exports 子目录
        export_dir = self.db_path.parent / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / export_filename

        try:
            # 复制数据库文件
            shutil.copy2(self.db_path, export_path)
            return {
                "success": True,
                "file_path": str(export_path),
                "size_bytes": export_path.stat().st_size
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def rebuild_index(self) -> Dict[str, Any]:
        """重建数据库索引。"""
        conn = self.get_db_connection()
        try:
            # 执行 REINDEX（重建所有索引）
            conn.execute("REINDEX")
            conn.commit()

            # 执行 VACUUM（压缩数据库）
            conn.execute("VACUUM")

            return {"success": True}
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            conn.close()

    # ==================== 任务管理 ====================

    def create_task(
        self,
        entity_id: str,
        target_period: str,
        task_type: str = "generation_annual",
        source_type: str = "automatic",
        user_specified_source: Optional[str] = None
    ) -> Dict[str, Any]:
        """创建一个待处理的采集任务。

        Args:
            entity_id: 电站 ID
            target_period: 目标年份（如 "2024"）
            task_type: 任务类型（默认 "generation_annual"）
            source_type: 来源类型 'manual' | 'automatic' | 'intelligent'
            user_specified_source: 用户指定的URL或文件路径 (D01/D10修复)

        Returns:
            {"task_id": str, "status": "pending"}
        """
        from hydro_platform.common.clock import now_iso
        from hydro_platform.common.enums import TaskType
        from hydro_platform.models.task import Task

        conn = self.get_db_connection()
        try:
            # 转换为枚举类型
            task_type_enum = TaskType.STATION_GENERATION if task_type == "generation_annual" else TaskType.STATION_GENERATION

            # 使用 Task 模型的幂等 ID 生成方法
            task_id = Task.derive_id(entity_id, task_type_enum, target_period)

            # 检查任务是否已存在
            existing = conn.execute(
                "SELECT task_id, status FROM tasks WHERE task_id = ?",
                (task_id,)
            ).fetchone()

            if existing:
                return {
                    "success": False,
                    "error": f"该任务已存在（状态: {existing['status']}）",
                    "task_id": existing["task_id"],
                    "status": existing["status"]
                }

            # 创建任务
            now = now_iso()
            conn.execute(
                """INSERT INTO tasks (
                    task_id, entity_id, entity_type, task_type,
                    target_period, status, source_type, user_specified_source,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, entity_id, "station", task_type_enum.value,
                 target_period, "pending", source_type, user_specified_source, now, now)
            )
            conn.commit()

            return {
                "success": True,
                "task_id": task_id,
                "status": "pending"
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            conn.close()

    # ==================== 统一可信导入入口（阶段 1）====================

    def run_collection_task(
        self,
        *,
        entity_id: str,
        target_period: str,
        url: Optional[str] = None,
        local_file: Optional[str] = None,
        source_title: Optional[str] = None,
        publisher: Optional[str] = None,
        expected: ContentKind = ContentKind.ANY,
    ) -> Dict[str, Any]:
        """统一可信导入入口：创建任务 → 走完整 Pipeline。

        Args:
            entity_id: 实体 ID（必需）
            target_period: 目标期间（如 "2024"）
            url: 文档 URL（与 local_file 二选一）
            local_file: 本地文件路径（与 url 二选一）
            source_title: 来源标题
            publisher: 发布者
            expected: 期望内容类型。默认自动识别；只有调用方确实需要限制
                单一格式时才应显式传入具体类型。

        Returns:
            {
                "status": "success" | "needs_review" | "failed",
                "task_id": str,
                "final_status": str,
                "documents_archived": int,
                "candidates_extracted": int,
                "candidates_promoted": int,
                "review_ids": list,
                "error": str | None
            }

        Raises:
            ValueError: 参数错误（url 和 local_file 都未提供或同时提供）
        """
        from hydro_platform.models.task import Task
        from hydro_platform.common.enums import EntityType, TaskType
        from hydro_platform.pipeline.orchestrator import run_task
        from hydro_platform.pipeline.context import PipelineContext, SourceRef
        from hydro_platform.acquisition.router import AcquisitionRouter
        from hydro_platform.acquisition.http_client import HttpClient
        from hydro_platform.acquisition.local_router import LocalFileRouter
        from hydro_platform.tasking.manager import TaskManager

        # 参数校验
        if not url and not local_file:
            raise ValueError("必须提供 url 或 local_file 之一")
        if url and local_file:
            raise ValueError("url 和 local_file 不能同时提供")

        # 创建任务
        task_id = Task.derive_id(entity_id, TaskType.STATION_GENERATION, target_period)
        ref_url = url if url else f"file://{Path(local_file).absolute()}"
        conn = self.get_db_connection()

        try:
            tm = TaskManager(conn)

            # 确保任务存在（幂等创建）
            task = Task(
                task_id=task_id,
                entity_id=entity_id,
                entity_type=EntityType.STATION,
                task_type=TaskType.STATION_GENERATION,
                target_period=target_period,
                source_type="manual",
                user_specified_source=ref_url,
            )
            tm.repo.upsert_many([task])  # 幂等：已存在则更新
            # 手动 URL / 本地文件是用户对本次采集的明确重新提交。若同一
            # (电站、指标、年份) 的历史任务曾被取消，应新开一轮执行，而不能
            # 让编排器把 cancelled 终态误报为“失败但没有原因”。
            tm.reopen_cancelled_for_explicit_source(task_id)

            # 构造 Pipeline 上下文
            router = self._build_acquisition_router()

            # URL Resolver：直接返回用户提供的 URL 或本地文件
            class SimpleResolver:
                def __init__(self, source_ref):
                    self.ref = source_ref
                def resolve(self, task):
                    return [self.ref]

            source_ref = SourceRef(
                url=ref_url,
                expected=expected,
                title=source_title,
                publisher=publisher,
            )

            ctx = PipelineContext(
                conn=conn,
                router=router,
                url_resolver=SimpleResolver(source_ref),
                raw_root=self.raw_root,
                use_llm=False,
                reviewer="desktop_app"
            )

            # 运行 Pipeline
            result = run_task(ctx, task)

            # 返回结构化结果
            return {
                "status": "success" if result.succeeded else ("needs_review" if result.needs_review else "failed"),
                "task_id": task_id,
                "final_status": result.final_status.value,
                "documents_archived": result.documents_archived,
                "candidates_extracted": result.candidates_extracted,
                "candidates_promoted": result.candidates_promoted,
                "review_ids": result.review_ids,
                "promoted_keys": result.promoted_keys,
                "error": result.error,
                "failure_stage": result.failure_stage.value if result.failure_stage else None
            }

        finally:
            conn.close()

    # ==================== 已隔离的历史辅助代码 ====================
    # 这些私有函数不再是应用 API，也不被桌面端调用。保留它们仅供迁移期
    # 的源码追溯；所有新代码必须调用 run_collection_task()。

    def _legacy_download_and_archive(
        self,
        url: str,
        source_id: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """【已废弃】下载并归档文档（采集 + 归档）。

        警告：此方法绕过 Validation/Evidence/Review 流程。
        生产环境请使用 run_collection_task() 统一入口。

        Args:
            url: 文档 URL
            source_id: 来源 ID
            metadata: 额外元数据（publisher, source_tier 等）

        Returns:
            {
                "document_id": str,
                "local_path": str,
                "sha256": str
            }

        Raises:
            BridgeError: 下载或归档失败
        """
        # 1. 采集
        router = AcquisitionRouter(http_client=HttpClient())
        fetch_result = router.fetch(url, expected=ContentKind.PDF)

        if not fetch_result.success:
            raise wrap_acquisition_error(fetch_result, url)

        # 2. 先注册来源（幂等操作，已存在则跳过）
        conn = self.get_db_connection()
        from hydro_platform.database.repositories import SourceRepository
        from hydro_platform.models.source import Source
        from hydro_platform.common.clock import now_iso

        source_repo = SourceRepository(conn)

        # 从 (url, content_hash) 派生真正的 source_id
        derived_source_id = source_repo.derive_id(url, fetch_result.meta.content_hash)

        # 注册来源（已存在则跳过）
        try:
            source = Source(
                source_id=derived_source_id,  # 使用派生的ID
                url=url,
                title=metadata.get("title", f"来源文档"),
                publisher=source_id,  # 用户输入的名称作为发布者
                publish_date=metadata.get("publish_date"),
                retrieved_at=now_iso(),
                content_hash=fetch_result.meta.content_hash,
                archive_path=None,  # 归档后更新
                language=metadata.get("language", "zh")
            )
            source_repo.register(source)
            conn.commit()
        except sqlite3.IntegrityError as e:
            # UNIQUE (url, content_hash) 约束失败 = 来源已存在，这是正常情况
            if "UNIQUE constraint" in str(e):
                pass  # 跳过，使用现有的来源记录
            else:
                raise  # 其他完整性错误需要抛出

        # 3. 归档（使用派生的 source_id）
        archiver = Archiver(conn, raw_root=self.raw_root)
        try:
            archive_result = archiver.archive(
                fetch_result,
                entity_id=None,
                task_id=None,
                source_id=derived_source_id  # 使用派生的ID
            )
            return {
                "document_id": archive_result.document.document_id,
                "local_path": str(archive_result.local_path),
                "sha256": archive_result.document.content_hash
            }
        except sqlite3.IntegrityError as e:
            # 外键约束失败：source_id 不存在
            error_msg = str(e).lower()
            if "foreign key" in error_msg:
                raise BridgeError(
                    stage="ARCHIVE",
                    code="SOURCE_NOT_FOUND",
                    message=f"数据源 '{source_id}' 不存在",
                    details={"url": url, "source_id": source_id}
                )
            # 其他完整性错误
            raise BridgeError(
                stage="ARCHIVE",
                code="INTEGRITY_ERROR",
                message=f"数据库完整性错误：{e}",
                details={"url": url, "source_id": source_id}
            )
        except ArchiveError as e:
            raise wrap_archive_error(e, {"url": url, "source_id": source_id})
        finally:
            conn.close()

    def _legacy_archive_local_file(
        self,
        file_path: str,
        source_id: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """【已废弃】归档本地文件。

        警告：此方法绕过 Validation/Evidence/Review 流程。
        生产环境请使用 run_collection_task() 统一入口。

        Args:
            file_path: 本地文件路径
            source_id: 来源 ID
            metadata: 额外元数据

        Returns:
            {
                "document_id": str,
                "local_path": str
            }

        Raises:
            BridgeError: 归档失败
        """
        from hydro_platform.acquisition.local_router import LocalFileRouter

        # 使用 LocalFileRouter 读取本地文件
        local_router = LocalFileRouter()
        fetch_result = local_router.fetch(file_path, expected=ContentKind.ANY)

        if not fetch_result.success:
            raise wrap_acquisition_error(fetch_result, file_path)

        # 归档
        conn = self.get_db_connection()
        archiver = Archiver(conn, raw_root=self.raw_root)
        try:
            archive_result = archiver.archive(
                fetch_result,
                entity_id=None,
                task_id=None,
                source_id=source_id
            )
            return {
                "document_id": archive_result.document.document_id,
                "local_path": str(archive_result.local_path)
            }
        except ArchiveError as e:
            raise wrap_archive_error(e, {"file_path": file_path, "source_id": source_id})
        finally:
            conn.close()

    def _legacy_parse_file(self, local_path: str) -> Any:
        """【已废弃】解析文档。

        警告：此方法绕过完整 Pipeline 流程。
        生产环境请使用 run_collection_task() 统一入口。

        Args:
            local_path: 本地文件路径

        Returns:
            ParsedContent 对象

        Raises:
            BridgeError: 解析失败
        """
        kind = self._legacy_guess_content_kind(local_path)
        content_type = self._legacy_content_type_from_kind(kind)

        parsed = parse_document(Path(local_path), kind=kind, content_type=content_type)

        if not parsed.ok:
            raise wrap_parse_error(parsed, local_path)

        return parsed

    def _legacy_extract_file(self, parsed_content: Any, source_id: str) -> Dict[str, Any]:
        """【已废弃】抽取结构化数据。

        警告：此方法绕过 Validation/Evidence/Review 流程。
        生产环境请使用 run_collection_task() 统一入口。

        Args:
            parsed_content: ParsedContent 对象
            source_id: 来源 ID

        Returns:
            {
                "generation_records": [
                    {
                        "generation_gwh": float,
                        "value_raw": str,
                        "unit_raw": str,
                        "snippet": str,
                        "confidence": str,
                        "warnings": list
                    },
                    ...
                ]
            }

        Raises:
            BridgeError: 抽取失败（无候选或全部无效）
        """
        candidates = extract_candidates(
            parsed_content,
            entity_id=None,
            task_id=None,
            source_id=source_id
        )

        if not candidates:
            raise wrap_extraction_error(
                "未找到有效发电量数据",
                {"source_id": source_id}
            )

        # 检查是否全部无效
        valid_count = sum(1 for c in candidates if c.generation_gwh is not None)
        if valid_count == 0:
            raise wrap_extraction_error(
                "所有候选结果均无有效发电量值",
                {"source_id": source_id, "candidate_count": len(candidates)}
            )

        # 转换为桌面应用期望的格式
        return {
            "generation_records": [
                {
                    "generation_gwh": c.generation_gwh,
                    "value_raw": c.value_raw,
                    "unit_raw": c.unit_raw,
                    "snippet": c.snippet,
                    "confidence": "high" if not c.flags else "low",
                    "warnings": c.flags
                }
                for c in candidates
            ]
        }

    # ==================== LLM 配置管理 API ====================

    def get_llm_config(self) -> Dict[str, Any]:
        """获取 LLM 配置状态。

        Returns:
            {
                "configured": bool,
                "provider": str (if configured),
                "model": str (if configured),
                "name": str (if configured),
                "configs": list[dict] (所有配置列表),
                "config_path": str
            }
        """
        from hydro_platform.config.llm_config import LLMConfig

        config = LLMConfig()
        deepseek = config.get_deepseek_config()
        configs = config.list_deepseek_configs()

        if deepseek and deepseek.get("api_key"):
            return {
                "configured": True,
                "provider": "DeepSeek",
                "model": deepseek.get("model", "deepseek-chat"),
                "name": deepseek.get("name", "default"),
                "configs": configs,
                "config_path": config.get_config_path(),
                "credential_backend": config.get_credential_backend(),
            }
        else:
            return {
                "configured": False,
                "configs": configs,
                "config_path": config.get_config_path(),
                "credential_backend": config.get_credential_backend(),
            }

    def save_llm_config(
        self,
        provider: str,
        api_key: str,
        model: Optional[str] = None,
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """保存 LLM 配置。

        Args:
            provider: 提供商名称（当前仅支持 "deepseek"）
            api_key: API Key
            model: 模型名称（可选，使用默认值）
            name: 配置名称（可选，默认为 "default"）

        Returns:
            {
                "success": bool,
                "message": str,
                "error": str (if failed)
            }
        """
        from hydro_platform.config.llm_config import LLMConfig

        if provider.lower() != "deepseek":
            return {
                "success": False,
                "error": f"暂不支持提供商：{provider}（当前仅支持 DeepSeek）"
            }

        try:
            config = LLMConfig()
            config.save_deepseek_key(
                api_key=api_key,
                model=model or "deepseek-v4-flash",
                name=name or "default"
            )
            return {
                "success": True,
                "message": "API Key 保存成功"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"保存失败：{str(e)}"
            }

    def switch_llm_config(self, provider: str, name: str) -> Dict[str, Any]:
        """切换活动的 LLM 配置。

        Args:
            provider: 提供商名称（当前仅支持 "deepseek"）
            name: 配置名称

        Returns:
            {
                "success": bool,
                "error": str (if failed)
            }
        """
        from hydro_platform.config.llm_config import LLMConfig

        if provider.lower() != "deepseek":
            return {
                "success": False,
                "error": f"暂不支持提供商：{provider}"
            }

        try:
            config = LLMConfig()
            success = config.switch_deepseek_config(name)
            if success:
                return {"success": True}
            else:
                return {
                    "success": False,
                    "error": f"配置 '{name}' 不存在"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"切换失败：{str(e)}"
            }

    def delete_llm_config(self, provider: str, name: str) -> Dict[str, Any]:
        """删除指定的 LLM 配置。

        Args:
            provider: 提供商名称（当前仅支持 "deepseek"）
            name: 配置名称

        Returns:
            {
                "success": bool,
                "error": str (if failed)
            }
        """
        from hydro_platform.config.llm_config import LLMConfig

        if provider.lower() != "deepseek":
            return {
                "success": False,
                "error": f"暂不支持提供商：{provider}"
            }

        try:
            config = LLMConfig()
            success = config.delete_deepseek_config(name)
            if success:
                return {"success": True}
            else:
                return {
                    "success": False,
                    "error": f"配置 '{name}' 不存在"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"删除失败：{str(e)}"
            }

    def test_llm_connection(self) -> Dict[str, Any]:
        """测试 LLM 连接。

        Returns:
            {
                "success": bool,
                "message": str,
                "model": str (if success),
                "error": str (if failed)
            }
        """
        from hydro_platform.config.llm_config import LLMConfig
        from hydro_platform.llm.deepseek_client import create_client_from_config

        config = LLMConfig()
        deepseek = config.get_deepseek_config()

        if not deepseek:
            return {
                "success": False,
                "error": "未配置 DeepSeek API Key"
            }

        client = create_client_from_config(deepseek)
        if not client:
            return {
                "success": False,
                "error": "配置无效或未启用"
            }

        return client.test_connection()

    def _legacy_save_candidates_to_database(
        self,
        candidates: list,
        document_id: str,
        source_id: str,
        entity_id: str = None,
        task_id: str = None
    ) -> Dict[str, Any]:
        """【已废弃】将抽取的候选记录保存到数据库。

        警告：此方法直接写库，绕过 Validation/Evidence/Review/Promotion 流程。
        生产环境请使用 run_collection_task() 统一入口。

        Args:
            candidates: 候选记录列表（extract_file 的返回格式）
            document_id: 文档 ID
            source_id: 来源 ID
            entity_id: 实体 ID（可选）
            task_id: 任务 ID（可选）

        Returns:
            {
                "saved": int,
                "skipped": int,
                "needs_review": int,
                "record_ids": list
            }
        """
        from hydro_platform.app.writer import RecordWriter

        conn = self.get_db_connection()
        try:
            writer = RecordWriter(conn)
            result = writer.save_candidates(
                candidates=candidates,
                document_id=document_id,
                source_id=source_id,
                entity_id=entity_id,
                task_id=task_id
            )
            return result
        finally:
            conn.close()

    def _legacy_guess_content_kind(self, file_path: str) -> ContentKind:
        """根据文件扩展名推断 ContentKind。"""
        ext = Path(file_path).suffix.lower()
        KIND_MAP = {
            ".pdf": ContentKind.PDF,
            ".xlsx": ContentKind.EXCEL,
            ".xls": ContentKind.EXCEL,
            ".csv": ContentKind.CSV,
            ".html": ContentKind.HTML,
            ".htm": ContentKind.HTML,
            ".json": ContentKind.JSON,
        }
        return KIND_MAP.get(ext, ContentKind.PDF)  # 默认 PDF

    def _legacy_content_type_from_kind(self, kind: ContentKind) -> str:
        """从 ContentKind 推断 Content-Type。"""
        TYPE_MAP = {
            ContentKind.PDF: "application/pdf",
            ContentKind.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ContentKind.CSV: "text/csv",
            ContentKind.HTML: "text/html",
            ContentKind.JSON: "application/json",
        }
        return TYPE_MAP.get(kind, "application/octet-stream")

    def execute_scheduled_task(self, task_id: str) -> Dict[str, Any]:
        """执行调度器触发的任务

        TaskScheduler调用此方法执行pending任务。
        根据任务类型和已有来源信息执行完整Pipeline。

        Args:
            task_id: 任务ID

        Returns:
            {
                "status": "success" | "needs_review" | "failed",
                "task_id": str,
                "final_status": str,
                ...
            }
        """
        from hydro_platform.tasking.manager import TaskManager
        from hydro_platform.models.task import Task
        from hydro_platform.pipeline.orchestrator import run_task
        from hydro_platform.pipeline.context import PipelineContext
        from hydro_platform.acquisition.router import AcquisitionRouter
        from hydro_platform.acquisition.http_client import HttpClient
        from hydro_platform.registry.source_registry import SourceRegistry
        from hydro_platform.discovery.resolver import DiscoveryResolver
        import os

        conn = self.get_db_connection()

        try:
            # 1. 加载任务
            tm = TaskManager(conn)
            task_row = tm.repo.get(task_id)

            if not task_row:
                return {
                    "status": "failed",
                    "task_id": task_id,
                    "error": f"任务不存在: {task_id}"
                }
            task = Task.model_validate(dict(task_row))

            # 2. 准备自动来源发现。真正解析延后到 Pipeline 领取任务之后执行，
            # 这样任务状态、审计与取消逻辑覆盖完整发现链路。
            deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
            resolver = DiscoveryResolver(conn, deepseek_api_key=deepseek_key)

            class AutomaticSourceResolver:
                """让 source_resolver 在历史来源后执行 Discovery 的空受控解析器。"""
                def resolve(self, _task):
                    return []

            # 3. 构造Pipeline上下文
            router = self._build_acquisition_router()

            ctx = PipelineContext(
                router=router,
                conn=conn,
                url_resolver=AutomaticSourceResolver(),
                discovery_resolver=resolver,
                raw_root=self.raw_root,
            )

            # 4. 执行Pipeline
            result = run_task(ctx, task)
            return {
                "status": "success" if result.succeeded else ("needs_review" if result.needs_review else "failed"),
                "task_id": task_id,
                "final_status": result.final_status.value,
                "documents_archived": result.documents_archived,
                "candidates_extracted": result.candidates_extracted,
                "candidates_promoted": result.candidates_promoted,
                "review_ids": result.review_ids,
                "promoted_keys": result.promoted_keys,
                "error": result.error,
                "failure_stage": result.failure_stage.value if result.failure_stage else None,
            }

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[API] execute_scheduled_task失败: {e}\n{tb}")

            return {
                "status": "failed",
                "task_id": task_id,
                "error": str(e),
                "traceback": tb
            }
        finally:
            conn.close()

    def import_csv_batch(self, csv_content: str, source_title: str = "CSV批量导入") -> Dict[str, Any]:
        """把 CSV 作为候选导入并送入复核，不直接写入正式事实。

        必填列：``entity_id, period_label, generation_gwh``。每行都会形成
        Candidate→Evidence→Document 链路和一个 ReviewItem；重复导入使用稳定
        哈希幂等，未知电站、非法年份和非法数值只进入错误明细。
        """
        import csv
        import hashlib
        import io
        import math
        import json

        from hydro_platform.common.enums import EntityType, Severity, TaskStatus, TaskType
        from hydro_platform.common.clock import now_iso
        from hydro_platform.database.repositories import TaskRepository
        from hydro_platform.models.candidate import ExtractionCandidate
        from hydro_platform.models.task import Task
        from hydro_platform.pipeline.candidate_evidence_binding import (
            CandidateEvidenceError,
        )
        from hydro_platform.review.queue import ReviewQueue
        from hydro_platform.validation.engine import ValidationContext, validate_candidate

        conn = self.get_db_connection()
        imported_count = 0
        existing_count = 0
        skipped_count = 0
        errors: list[str] = []
        details: list[dict] = []
        try:
            rows = list(csv.DictReader(io.StringIO(csv_content, newline="")))
            if not rows:
                return {"success": False, "imported_count": 0, "skipped_count": 0,
                        "errors": ["CSV文件为空"], "details": []}

            required = {"entity_id", "period_label", "generation_gwh"}
            columns = set(rows[0].keys())
            missing = sorted(required - columns)
            if missing:
                return {"success": False, "imported_count": 0, "skipped_count": 0,
                        "errors": [f"缺少必填列: {', '.join(missing)}"], "details": []}

            content_hash = hashlib.sha256(csv_content.encode("utf-8")).hexdigest()
            source_id = f"csv_{content_hash[:24]}"
            document_id = f"doc_{content_hash[:24]}"
            now = now_iso()
            conn.execute(
                """INSERT INTO sources
                (source_id, url, title, publisher, retrieved_at, content_hash,
                 source_type, document_type, access_method, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'manual', 'csv', 'upload', ?, ?)
                ON CONFLICT(source_id) DO NOTHING""",
                (source_id, f"csv://{source_id}", source_title, "用户导入", now,
                 content_hash, now, now),
            )
            conn.execute(
                """INSERT INTO documents
                (document_id, source_id, original_url, content_type, content_kind,
                 file_size, content_hash, local_path, access_method, created_at)
                VALUES (?, ?, ?, 'text/csv', 'csv', ?, ?, ?, 'upload', ?)
                ON CONFLICT(document_id) DO NOTHING""",
                (document_id, source_id, f"csv://{source_id}",
                 len(csv_content.encode("utf-8")), content_hash,
                 f"inline://{source_id}", now),
            )

            queue = ReviewQueue(conn)
            for idx, row in enumerate(rows, start=1):
                try:
                    entity_id = (row.get("entity_id") or "").strip()
                    period_label = (row.get("period_label") or "").strip()
                    raw_value = (row.get("generation_gwh") or "").strip()
                    if not entity_id or not period_label or not raw_value:
                        raise ValueError("必填字段为空")
                    if not period_label.isdigit() or len(period_label) != 4:
                        raise ValueError("period_label 必须是四位日历年")
                    period_type = (row.get("period_type") or "calendar_year").strip()
                    value_type = (row.get("value_type") or "actual").strip().casefold()
                    measurement_scope = (row.get("measurement_scope") or "plant").strip().casefold()
                    if period_type != "calendar_year":
                        raise ValueError("CSV 导入只接受 calendar_year")
                    if value_type != "actual":
                        raise ValueError("CSV 导入不接受 forecast/estimate 等非实际值")
                    if measurement_scope != "plant":
                        raise ValueError("CSV 导入只接受 plant 单站口径")
                    generation_gwh = float(raw_value)
                    if not math.isfinite(generation_gwh) or generation_gwh < 0:
                        raise ValueError("generation_gwh 必须是非负有限数字")

                    station = conn.execute(
                        "SELECT canonical_name, capacity_mw FROM stations WHERE entity_id = ?",
                        (entity_id,),
                    ).fetchone()
                    if station is None:
                        raise ValueError(f"未知电站: {entity_id}")

                    value_raw = (row.get("value_raw") or raw_value).strip()
                    unit_raw = (row.get("unit_raw") or "GWh").strip()
                    valid_energy_units = {
                        "gwh", "mwh", "twh", "kwh", "亿千瓦时", "万千瓦时", "千瓦时"
                    }
                    if unit_raw.casefold() not in valid_energy_units:
                        raise ValueError(f"unit_raw 不是受支持的能量单位: {unit_raw}")
                    confidence_text = (row.get("confidence") or "").strip()
                    confidence = float(confidence_text) if confidence_text else None
                    if confidence is not None and not 0 <= confidence <= 1:
                        raise ValueError("confidence 必须在 0 到 1 之间")
                    snippet = (
                        f"CSV row {idx}: {entity_id}, {period_label}, "
                        f"{generation_gwh:g} {unit_raw}"
                    )
                    canonical_payload = {
                        "document_id": document_id,
                        "entity_id": entity_id,
                        "period_label": period_label,
                        "period_type": period_type,
                        "value_type": value_type,
                        "measurement_scope": measurement_scope,
                        "generation_gwh": generation_gwh,
                        "value_raw": value_raw,
                        "unit_raw": unit_raw,
                        "row": idx,
                    }
                    candidate_id = "cand_" + hashlib.sha256(
                        json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()[:24]
                    evidence_id = "evi_" + hashlib.sha256(
                        f"{document_id}:{candidate_id}".encode("utf-8")
                    ).hexdigest()[:24]

                    # 每条 CSV 候选对应一个稳定的人工复核任务。目标期包含候选
                    # 摘要，既保留年份语义，又不会与自动采集任务发生唯一键冲突。
                    task_digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16]
                    task = Task(
                        task_id=f"manual_review::{task_digest}",
                        entity_id=entity_id,
                        entity_type=EntityType.STATION,
                        task_type=TaskType.USER_QUERY,
                        target_period=f"{period_label}::review::{task_digest}",
                        status=TaskStatus.NEEDS_REVIEW,
                        source_type="manual",
                        user_specified_source=f"csv://{source_id}",
                    )
                    TaskRepository(conn).upsert_many([task])
                    candidate_exists = conn.execute(
                        "SELECT 1 FROM extraction_candidates WHERE candidate_id = ?",
                        (candidate_id,),
                    ).fetchone() is not None

                    conn.execute(
                        """INSERT INTO evidence
                        (evidence_id, source_id, document_id, content_hash, fact_type,
                         fact_key, source_url, snippet, confidence, task_id, created_at)
                        VALUES (?, ?, ?, ?, 'generation', ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(evidence_id) DO UPDATE SET
                            task_id = COALESCE(evidence.task_id, excluded.task_id)""",
                        (evidence_id, source_id, document_id, content_hash,
                         f"{entity_id}:{period_label}:actual", f"csv://{source_id}",
                         snippet, confidence, task.task_id, now),
                    )
                    candidate = ExtractionCandidate(
                        candidate_id=candidate_id,
                        entity_id=entity_id,
                        period_type=period_type,
                        period_label=period_label,
                        generation_gwh=generation_gwh,
                        value_type=value_type,
                        measurement_scope=measurement_scope,
                        value_raw=value_raw,
                        unit_raw=unit_raw,
                        snippet=snippet,
                        confidence=confidence,
                        extractor="csv_import",
                        task_id=task.task_id,
                        source_id=source_id,
                    )
                    conn.execute(
                        """INSERT INTO extraction_candidates
                        (candidate_id, task_id, entity_id, document_id, period_type, period_label,
                         value_type, measurement_scope, generation_gwh, value_raw, unit_raw,
                         snippet, extraction_method, extracted_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'csv_import', ?)
                        ON CONFLICT(candidate_id) DO UPDATE SET
                            task_id = COALESCE(extraction_candidates.task_id, excluded.task_id)""",
                        (candidate_id, task.task_id, entity_id, document_id, period_type, period_label,
                         value_type, measurement_scope, generation_gwh, value_raw, unit_raw, snippet, now),
                    )
                    conn.execute(
                        """INSERT INTO candidate_evidence(candidate_id, evidence_id)
                        VALUES (?, ?) ON CONFLICT(candidate_id, evidence_id) DO NOTHING""",
                        (candidate_id, evidence_id),
                    )

                    validation = validate_candidate(
                        candidate,
                        ValidationContext(
                            entity_capacity_mw=station["capacity_mw"],
                            expected_year=int(period_label),
                        ),
                    )
                    validation.add_issue(
                        "CSV_IMPORT_REVIEW",
                        "CSV 导入数据必须经过人工复核后才能发布",
                        Severity.MEDIUM,
                    )
                    supplied_name = (row.get("canonical_name") or "").strip()
                    if supplied_name and supplied_name != station["canonical_name"]:
                        validation.add_issue(
                            "ENTITY_AMBIGUOUS",
                            f"CSV名称 {supplied_name!r} 与主数据名称不一致",
                            Severity.HIGH,
                            "canonical_name",
                        )
                    review_id = queue.submit(candidate, validation, evidence_ids=[evidence_id])
                    if not review_id:
                        raise CandidateEvidenceError("CSV 候选未进入复核队列")

                    if candidate_exists:
                        existing_count += 1
                    else:
                        imported_count += 1
                    details.append({
                        "row": idx,
                        "entity_id": entity_id,
                        "period": period_label,
                        "generation_gwh": generation_gwh,
                        "candidate_id": candidate_id,
                        "review_id": review_id,
                        "task_id": task.task_id,
                        "status": "already_queued" if candidate_exists else "queued_for_review",
                    })
                except Exception as exc:
                    skipped_count += 1
                    errors.append(f"第{idx}行: {exc}")

            conn.commit()
            return {
                "success": imported_count > 0 or existing_count > 0,
                "imported_count": imported_count,
                "existing_count": existing_count,
                "skipped_count": skipped_count,
                "errors": errors[:10],
                "details": details,
            }
        except Exception as exc:
            conn.rollback()
            return {
                "success": False,
                "imported_count": 0,
                "skipped_count": 0,
                "errors": [f"导入失败: {exc}"],
                "details": [],
            }
        finally:
            conn.close()

    # ==================== 统一可信来源发现（不创建采集任务）====================

    def discover_trusted_sources(
        self,
        entity_id: str,
        target_period: str,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """融合实际搜索、DeepSeek 原生搜索与 GEM 外链，返回可信候选。

        此接口只能更新 ``source_discoveries`` 候选台账；绝不下载正式资料、
        绝不创建任务、绝不写入 ``sources`` 或发电量事实表。
        """
        from hydro_platform.config.llm_config import LLMConfig
        from hydro_platform.intelligence.deepseek_agent import DeepSeekResponsesAgent

        if not entity_id or not target_period:
            return {"success": False, "error": "必须提供电站 ID 和四位目标年份", "items": []}
        try:
            year = int(target_period)
        except (TypeError, ValueError):
            return {"success": False, "error": "目标年份必须是四位年份", "items": []}
        if not 1900 <= year <= 2100:
            return {"success": False, "error": "目标年份必须是四位年份", "items": []}

        deepseek = LLMConfig().get_deepseek_config()
        if not deepseek or not deepseek.get("api_key"):
            return {"success": False, "error": "未配置 DeepSeek API Key，请先在设置中配置并测试连接", "items": []}
        agent_model = deepseek.get("model") or "deepseek-v4-flash"
        agent = DeepSeekResponsesAgent(api_key=deepseek["api_key"], model=agent_model)

        conn = self.get_db_connection()
        try:
            station = conn.execute(
                """SELECT entity_id, canonical_name, local_name, aliases, country, operator, owner, gem_wiki_url
                   FROM stations WHERE entity_id = ?""",
                (entity_id,),
            ).fetchone()
            if station is None:
                return {"success": False, "error": f"未找到电站: {entity_id}", "items": []}
            station = dict(station)
            intent = self._station_search_intent(station, str(year))
            items, review_items, warnings, audited_count = self._discover_trusted_source_candidates(
                conn, station=station, intent=intent, agent=agent,
            )
            display_limit = max(1, min(int(limit), 10))
            items = items[:display_limit]
            if items:
                recommendation = items[0]
                message = (
                    f"已融合 DeepSeek 原生搜索、程序搜索和 GEM 外链，审计 {audited_count} 个候选；"
                    f"{len(items)} 个通过电站、年份、年度发电量和访问校验。"
                )
            else:
                recommendation = None
                message = "已完成多通道搜索，但没有候选通过电站、年份、年度发电量和访问校验；未创建采集任务。"
            if warnings:
                message += " " + "；".join(warnings)
            return {
                "success": True, "entity_id": entity_id, "entity_name": station["canonical_name"],
                "target_period": str(year), "items": items, "review_items": review_items, "recommendation": recommendation,
                "message": message, "search_channels": ["deepseek_native", "program_search", "gem_external"],
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "items": []}
        finally:
            conn.close()

    def discover_official_sources(self, entity_id: str, target_period: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """兼容旧桌面缓存的别名；不再执行旧的 GEM-only 发现逻辑。"""
        return self.discover_trusted_sources(entity_id, target_period or "", limit)
