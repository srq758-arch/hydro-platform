"""只读查询层：产品页面所需的所有 SELECT / 聚合查询集中于此。

设计原则（对齐 UI 基线文档）：
- API 层只调用本模块，不直接写 SQL；
- 所有计数/聚合都基于真实数据库，业务表为空时返回 0 或空列表，绝不造假；
- 只读：本模块不做任何 INSERT/UPDATE/DELETE；
- 返回普通 dict/list，便于直接 json 序列化给前端。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class ReadQueries:
    """面向产品页面的只读查询。传入一个已配置 row_factory 的连接。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ---- 通用计数 ----
    def _count(self, table: str, where: str = "", params: tuple = ()) -> int:
        sql = f"SELECT COUNT(*) AS n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return int(self.conn.execute(sql, params).fetchone()["n"])

    # ================= 工作台 Dashboard =================
    def get_dashboard(self) -> dict[str, Any]:
        """工作台首页所需的全部聚合数据（基线第 8 节）。"""
        return {
            "asset_cards": self._dashboard_asset_cards(),
            "quality": self._dashboard_quality(),
            "todo": self._dashboard_todo(),
            "gaps": self.list_data_gaps(limit=5),
            "recent": self._dashboard_recent(limit=4),
            "coverage_by_year": self._coverage_by_year(),
        }

    def _dashboard_asset_cards(self) -> dict[str, int]:
        """6 张数据资产卡片的数量。业务表为空时自然为 0。"""
        # 计算高优先级数据缺口数量（装机容量 >= 10000 MW 的电站的缺失年份）
        high_priority_gaps = 0
        try:
            stations = self.conn.execute(
                """
                SELECT entity_id, capacity_mw
                FROM stations
                WHERE capacity_mw >= 10000
                LIMIT 50
                """
            ).fetchall()

            for station in stations:
                entity_id = station['entity_id']
                existing_years = set(
                    row['period_label'] for row in self.conn.execute(
                        """
                        SELECT DISTINCT period_label
                        FROM generation_records
                        WHERE entity_id = ? AND publication_status = 'publishable'
                        """,
                        (entity_id,)
                    ).fetchall()
                )

                # 检测 2015-2024 年的缺口
                for year in range(2015, 2025):
                    if str(year) not in existing_years:
                        high_priority_gaps += 1
        except Exception:
            # 如果计算失败，使用待处理任务数作为后备
            high_priority_gaps = self._count("tasks", "status != ?", ("done",))

        return {
            "stations": self._count("stations"),
            "projects": self._count("projects"),
            "documents": self._count("documents"),
            "accepted_records": self._count(
                "generation_records", "publication_status = ?", ("publishable",)
            ),
            "data_gaps": high_priority_gaps,
            "pending_reviews": self._count("review_items", "status = ?", ("open",)),
        }

    def _dashboard_quality(self) -> dict[str, Any]:
        """数据质量概况：按 publication/review 状态分桶（环形图数据）。"""
        total = self._count("generation_records")
        publishable = self._count(
            "generation_records", "publication_status = ?", ("publishable",)
        )
        pending = self._count("review_items", "status = ?", ("open",))
        return {
            "total": total,
            "buckets": [
                {"key": "publishable", "label": "已确认记录", "count": publishable},
                {"key": "pending_review", "label": "待人工复核", "count": pending},
            ],
        }

    def _dashboard_todo(self) -> list[dict[str, Any]]:
        """当前需要处理：每行=问题类型+数量+下一步动作。"""
        return [
            {
                "key": "data_gaps",
                "label": "数据缺口（高优先级）",
                "count": self._count("tasks", "status = ?", ("pending",)),
                "action": "去处理",
                "route": "data-gaps",
            },
            {
                "key": "pending_reviews",
                "label": "待复核候选",
                "count": self._count("review_items", "status = ?", ("open",)),
                "action": "去复核",
                "route": "review",
            },
            {
                "key": "failed_tasks",
                "label": "采集失败任务",
                "count": self._count("tasks", "status = ?", ("failed",)),
                "action": "去重试",
                "route": "tasks",
            },
        ]

    def _dashboard_recent(self, limit: int = 4) -> list[dict[str, Any]]:
        """最近工作：以数据记录为中心（基线 8.5）。业务表空时为空列表。"""
        rows = self.conn.execute(
            """
            SELECT g.entity_id, g.period_label, g.value_type,
                   g.generation_gwh, g.review_status, g.publication_status,
                   g.updated_at, s.canonical_name
            FROM generation_records g
            LEFT JOIN stations s ON s.entity_id = g.entity_id
            ORDER BY g.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _coverage_by_year(self) -> list[dict[str, Any]]:
        """按年份的已确认记录数（覆盖率柱状图）。"""
        rows = self.conn.execute(
            """
            SELECT period_label AS year, COUNT(*) AS accepted
            FROM generation_records
            WHERE publication_status = 'publishable' AND period_type = 'year'
            GROUP BY period_label
            ORDER BY period_label
            """
        ).fetchall()
        return [dict(r) for r in rows]

    # ================= 水电站列表 =================
    def list_stations(
        self,
        *,
        search: Optional[str] = None,
        country: Optional[str] = None,
        status: Optional[str] = None,
        min_capacity: Optional[float] = None,
        max_capacity: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """水电站列表（基线第 9 节）：支持搜索/筛选/分页。返回 {total, items}。"""
        where: list[str] = []
        params: list[Any] = []

        if search:
            where.append(
                "(canonical_name LIKE ? OR aliases LIKE ? OR local_name LIKE ?)"
            )
            like = f"%{search}%"
            params += [like, like, like]
        if country:
            where.append("country = ?")
            params.append(country)
        if status:
            where.append("status = ?")
            params.append(status)
        if min_capacity is not None:
            where.append("capacity_mw >= ?")
            params.append(min_capacity)
        if max_capacity is not None:
            where.append("capacity_mw <= ?")
            params.append(max_capacity)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) AS n FROM stations{where_sql}", tuple(params)
            ).fetchone()["n"]
        )

        rows = self.conn.execute(
            f"""
            SELECT entity_id, canonical_name, country, state_province, river,
                   capacity_mw, status, operator, priority_tier
            FROM stations{where_sql}
            ORDER BY capacity_mw DESC NULLS LAST
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (limit, offset),
        ).fetchall()

        return {"total": total, "items": [dict(r) for r in rows]}

    def list_countries(self) -> list[dict[str, Any]]:
        """筛选下拉用：有电站的国家及其数量。"""
        rows = self.conn.execute(
            """
            SELECT country, COUNT(*) AS n FROM stations
            WHERE country IS NOT NULL AND country != ''
            GROUP BY country ORDER BY n DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    # ================= 水电站详情 =================
    def get_station_detail(self, entity_id: str) -> dict[str, Any] | None:
        """水电站详情（基线第 10 节）：基本信息 + 发电量 + 覆盖概览。"""
        print(f"[DEBUG] get_station_detail called with entity_id={entity_id}")
        station = _row_to_dict(
            self.conn.execute(
                "SELECT * FROM stations WHERE entity_id = ?", (entity_id,)
            ).fetchone()
        )
        if station is None:
            print(f"[DEBUG] Station not found for entity_id={entity_id}")
            return None

        generation = self.get_station_generation(entity_id)
        print(f"[DEBUG] Found {len(generation)} generation records")
        years = [g["period_label"] for g in generation]
        return {
            "station": station,
            "generation": generation,
            "coverage": {
                "record_count": len(generation),
                "years": years,
                "latest_year": max(years) if years else None,
            },
        }

    def get_station_generation(self, entity_id: str) -> list[dict[str, Any]]:
        """某电站的年度发电量记录（基线 10.2）。"""
        rows = self.conn.execute(
            """
            SELECT g.period_label, g.period_type, g.value_type, g.value_raw,
                   g.unit_raw, g.generation_gwh, g.review_status,
                   g.publication_status, g.validation_status, g.confidence,
                   g.source_id, g.evidence_id, s.title AS source_title
            FROM generation_records g
            LEFT JOIN sources s ON s.source_id = g.source_id
            WHERE g.entity_id = ?
            ORDER BY g.period_label DESC
            """,
            (entity_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ================= 数据缺口 =================
    def list_data_gaps(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """数据缺口列表（基线第 12 节）。当前以未完成 task 为缺口来源。

        业务尚未产生 task 时返回空列表——这是真实状态，不是错误。
        """
        rows = self.conn.execute(
            """
            SELECT t.task_id, t.entity_id, t.entity_type, t.target_period,
                   t.task_type, t.status, t.priority_tier, t.failure_stage,
                   t.last_error, t.updated_at,
                   COALESCE(s.canonical_name, p.canonical_name) AS name
            FROM tasks t
            LEFT JOIN stations s ON s.entity_id = t.entity_id
            LEFT JOIN projects p ON p.entity_id = t.entity_id
            WHERE t.status != 'done'
            ORDER BY t.collection_priority ASC NULLS LAST, t.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def detect_data_gaps(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """智能检测数据缺口：哪些高优先级电站缺少哪些年份的数据。

        算法：
        1. 取装机容量 >= 1000 MW 的电站（高优先级）
        2. 检查 2015-2024 年是否有已发布记录
        3. 返回缺失的 (entity_id, year) 组合
        """
        # 获取高优先级电站
        stations = self.conn.execute(
            """
            SELECT entity_id, canonical_name, capacity_mw, country
            FROM stations
            WHERE capacity_mw >= 1000
            ORDER BY capacity_mw DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

        gaps = []
        for station in stations:
            entity_id = station['entity_id']
            # 检查已有哪些年份
            existing_years = set(
                row['period_label'] for row in self.conn.execute(
                    """
                    SELECT DISTINCT period_label
                    FROM generation_records
                    WHERE entity_id = ? AND publication_status = 'publishable'
                    """,
                    (entity_id,)
                ).fetchall()
            )

            # 检测 2015-2024 年的缺口
            for year in range(2015, 2025):
                year_str = str(year)
                if year_str not in existing_years:
                    gaps.append({
                        'entity_id': entity_id,
                        'name': station['canonical_name'],
                        'country': station['country'],
                        'capacity_mw': station['capacity_mw'],
                        'target_year': year_str,
                        'priority': 'high' if station['capacity_mw'] >= 10000 else 'medium',
                        'gap_type': 'missing_year'
                    })

        return gaps

    def get_data_coverage_stats(self) -> dict[str, Any]:
        """数据覆盖率统计：按国家、年份的覆盖情况。"""
        # 按国家统计
        by_country = self.conn.execute(
            """
            SELECT s.country,
                   COUNT(DISTINCT s.entity_id) as total_stations,
                   COUNT(DISTINCT g.entity_id) as stations_with_data,
                   COUNT(DISTINCT g.id) as total_records
            FROM stations s
            LEFT JOIN generation_records g ON g.entity_id = s.entity_id
                AND g.publication_status = 'publishable'
            WHERE s.country IS NOT NULL
            GROUP BY s.country
            ORDER BY total_stations DESC
            LIMIT 20
            """
        ).fetchall()

        # 按年份统计
        by_year = self.conn.execute(
            """
            SELECT period_label as year,
                   COUNT(*) as record_count,
                   COUNT(DISTINCT entity_id) as station_count
            FROM generation_records
            WHERE publication_status = 'publishable'
                AND period_type = 'year'
            GROUP BY period_label
            ORDER BY period_label DESC
            LIMIT 15
            """
        ).fetchall()

        # 总体统计
        overall = self.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM stations) as total_stations,
                (SELECT COUNT(DISTINCT entity_id) FROM generation_records
                 WHERE publication_status = 'publishable') as stations_with_data,
                (SELECT COUNT(*) FROM generation_records
                 WHERE publication_status = 'publishable') as total_records
            """
        ).fetchone()

        return {
            'overall': dict(overall),
            'by_country': [dict(r) for r in by_country],
            'by_year': [dict(r) for r in by_year]
        }

    # ================= 数据浏览 =================
    def browse_records(
        self,
        *,
        entity_id: Optional[str] = None,
        year: Optional[str] = None,
        value_type: Optional[str] = None,
        published_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """数据浏览（基线 18.1）：跨电站浏览发电量记录，带筛选。"""
        where: list[str] = []
        params: list[Any] = []
        if entity_id:
            where.append("g.entity_id = ?")
            params.append(entity_id)
        if year:
            where.append("g.period_label = ?")
            params.append(year)
        if value_type:
            where.append("g.value_type = ?")
            params.append(value_type)
        if published_only:
            where.append("g.publication_status = 'publishable'")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) AS n FROM generation_records g{where_sql}",
                tuple(params),
            ).fetchone()["n"]
        )
        rows = self.conn.execute(
            f"""
            SELECT g.entity_id, s.canonical_name, s.country, g.period_label,
                   g.value_type, g.generation_gwh, g.publication_status,
                   g.review_status, g.source_id
            FROM generation_records g
            LEFT JOIN stations s ON s.entity_id = g.entity_id{where_sql}
            ORDER BY g.generation_gwh DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (limit, offset),
        ).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}

    # ================= Top 100 =================
    def get_top100(self, year: Optional[str] = None) -> list[dict[str, Any]]:
        """Top100（基线 18.2 + D04修复）：使用统一可信过滤器。

        必须满足完整可信标准：
        - value_type='actual', period_type='calendar_year', measurement_scope='plant'
        - validation_status='passed', publication_status='publishable', review_status='approved'
        - evidence_id IS NOT NULL
        """
        from hydro_platform.products.trustworthy_filter import get_top_n_trustworthy

        if not year:
            # 年份必须明确，防止混合不同年份
            # 默认使用最新有数据的年份
            latest = self.conn.execute(
                """SELECT DISTINCT period_label FROM generation_records
                   WHERE publication_status = 'publishable'
                   ORDER BY period_label DESC LIMIT 1"""
            ).fetchone()
            if not latest:
                return []
            year = latest['period_label']

        records = get_top_n_trustworthy(self.conn, year=year, n=100)

        # 补充容量信息
        for r in records:
            station = self.conn.execute(
                "SELECT capacity_mw FROM stations WHERE entity_id = ?",
                (r['entity_id'],)
            ).fetchone()
            if station:
                r['capacity_mw'] = station['capacity_mw']

        return records

    # ================= 复核中心 =================
    def list_review_items(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        """待复核记录列表 - 从 extraction_candidates 读取。

        D02修复：复核队列与pipeline数据流打通
        - 从 extraction_candidates 表读取候选
        - 通过 review_items 表关联复核状态
        - 显示候选来源（文件/URL/自动搜索）
        """
        where_clauses = []
        params: list[Any] = []

        # 根据状态筛选
        if status == "open":
            where_clauses.append("ri.status = 'open'")
        elif status == "approved":
            where_clauses.append("ri.status = 'approved'")
        elif status == "rejected":
            where_clauses.append("ri.status = 'rejected'")
        else:
            # 默认：只显示待复核的（open状态）
            where_clauses.append("ri.status = 'open'")

        where = " AND ".join(where_clauses) if where_clauses else "1=1"

        # 计数
        total = self.conn.execute(
            f"""
            SELECT COUNT(*) as n
            FROM review_items ri
            INNER JOIN extraction_candidates c ON ri.candidate_id = c.candidate_id
            WHERE {where}
            """,
            tuple(params)
        ).fetchone()["n"]

        # 查询记录 - 从 extraction_candidates 读取
        rows = self.conn.execute(
            f"""
            SELECT ri.review_id, ri.review_id AS id, ri.candidate_id, ri.status as review_status,
                   ri.created_at as review_created_at,
                   c.entity_id, c.task_id, c.document_id,
                   c.period_type, c.period_label, c.value_type, c.measurement_scope,
                   c.generation_gwh, c.value_raw, c.unit_raw,
                   c.snippet, c.extraction_method, c.extracted_at,
                   s.canonical_name, s.country, s.capacity_mw,
                   d.local_path as document_path, d.content_kind,
                   src.title as source_title, src.url as source_url,
                   src.access_method,
                   t.task_type, t.user_specified_source
            FROM review_items ri
            INNER JOIN extraction_candidates c ON ri.candidate_id = c.candidate_id
            LEFT JOIN stations s ON s.entity_id = c.entity_id
            LEFT JOIN documents d ON d.document_id = c.document_id
            LEFT JOIN sources src ON src.source_id = d.source_id
            LEFT JOIN tasks t ON t.task_id = c.task_id
            WHERE {where}
            ORDER BY ri.created_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (limit, offset)
        ).fetchall()

        # 增强结果：添加来源类型标签
        items = []
        for row in rows:
            item = dict(row)
            # 判断来源类型
            if item.get('user_specified_source'):
                item['source_type'] = 'user_upload' if item.get('access_method') == 'upload' else 'user_url'
            elif item.get('extraction_method') == 'auto_search':
                item['source_type'] = 'auto_search'
            else:
                item['source_type'] = 'pipeline'
            items.append(item)

        return {
            "total": total,
            "items": items,
            "limit": limit,
            "offset": offset
        }

    def get_review_detail(self, record_id: int | str) -> Optional[dict[str, Any]]:
        """按 review_id 获取详情；保留 generation_records.id 的旧兼容入口。"""
        import json

        # 新契约：review_id 是复核操作的唯一入口，不要求候选已经发布为事实。
        review = self.conn.execute(
            "SELECT * FROM review_items WHERE review_id = ?", (str(record_id),)
        ).fetchone()
        if review is not None:
            candidate = None
            if review["candidate_id"]:
                candidate = self.conn.execute(
                    "SELECT * FROM extraction_candidates WHERE candidate_id = ?",
                    (review["candidate_id"],),
                ).fetchone()
            if candidate is not None:
                result = dict(candidate)
                result.update({
                    "id": review["review_id"],
                    "review_id": review["review_id"],
                    "review_status": review["status"],
                    "review_reason": review["reason"],
                    "review_created_at": review["created_at"],
                    "validation_issues": [],
                })
                evidence = self.conn.execute(
                    """
                    SELECT e.*, d.local_path AS document_path,
                           src.title AS source_title, src.url AS source_url
                    FROM candidate_evidence ce
                    JOIN evidence e ON e.evidence_id = ce.evidence_id
                    LEFT JOIN documents d ON d.document_id = e.document_id
                    LEFT JOIN sources src ON src.source_id = d.source_id
                    WHERE ce.candidate_id = ?
                    ORDER BY e.evidence_id
                    """,
                    (candidate["candidate_id"],),
                ).fetchall()
                result["evidences"] = [dict(row) for row in evidence]
                if review["payload"]:
                    try:
                        result["validation_issues"] = json.loads(review["payload"]).get(
                            "validation_issues", []
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                station = self.conn.execute(
                    "SELECT canonical_name, country, capacity_mw FROM stations WHERE entity_id = ?",
                    (candidate["entity_id"],),
                ).fetchone()
                if station:
                    result.update(dict(station))
                return result

        # 兼容旧 GUI/CLI 传入 generation_records.id 的路径。
        row = self.conn.execute(
            """
            SELECT g.*, s.canonical_name, s.country, s.capacity_mw,
                   e.snippet, e.page_number, e.table_reference, e.locator,
                   e.confidence AS evidence_confidence,
                   src.title AS source_title, src.url AS source_url,
                   src.publisher, src.publish_date,
                   d.local_path AS document_path, d.content_type
            FROM generation_records g
            LEFT JOIN stations s ON s.entity_id = g.entity_id
            LEFT JOIN evidence e ON e.evidence_id = g.evidence_id
            LEFT JOIN sources src ON src.source_id = g.source_id
            LEFT JOIN documents d ON d.document_id = e.document_id
            WHERE g.id = ?
            """,
            (record_id,)
        ).fetchone()

        if not row:
            return None

        result = dict(row)

        # 查找对应的review_item获取validation_issues
        review_row = self.conn.execute(
            """
            SELECT payload FROM review_items
            WHERE entity_id = ? AND fact_type = 'generation' AND status = 'open'
            """,
            (result['entity_id'],)
        ).fetchone()

        if review_row and review_row['payload']:
            try:
                payload = json.loads(review_row['payload'])
                result['validation_issues'] = payload.get('validation_issues', [])
            except (json.JSONDecodeError, KeyError):
                result['validation_issues'] = []
        else:
            result['validation_issues'] = []

        return result

    # ================= 来源管理 =================
    def list_sources(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """来源列表：显示所有数据来源及其统计。"""
        rows = self.conn.execute(
            """
            SELECT s.source_id, s.title, s.url, s.publisher,
                   s.publish_date, s.retrieved_at,
                   COUNT(DISTINCT d.document_id) as document_count,
                   COUNT(DISTINCT g.id) as record_count
            FROM sources s
            LEFT JOIN documents d ON d.source_id = s.source_id
            LEFT JOIN generation_records g ON g.source_id = s.source_id
            GROUP BY s.source_id
            ORDER BY record_count DESC, s.publish_date DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset)
        ).fetchall()

        total = self._count("sources")
        return {"total": total, "items": [dict(r) for r in rows]}

    # ================= 文档资料 =================
    def list_documents(
        self,
        source_id: Optional[str] = None,
        content_kind: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        """文档列表：显示所有归档的文档。"""
        where: list[str] = []
        params: list[Any] = []

        if source_id:
            where.append("d.source_id = ?")
            params.append(source_id)
        if content_kind:
            where.append("d.content_kind = ?")
            params.append(content_kind)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) AS n FROM documents d{where_sql}",
                tuple(params)
            ).fetchone()["n"]
        )

        rows = self.conn.execute(
            f"""
            SELECT d.document_id, d.source_id, d.content_kind, d.content_type,
                   d.file_size, d.content_hash, d.local_path,
                   d.fetched_at, d.created_at,
                   s.title as source_title,
                   COUNT(DISTINCT e.evidence_id) as record_count
            FROM documents d
            LEFT JOIN sources s ON s.source_id = d.source_id
            LEFT JOIN evidence e ON e.document_id = d.document_id{where_sql}
            GROUP BY d.document_id
            ORDER BY d.fetched_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (limit, offset)
        ).fetchall()

        return {"total": total, "items": [dict(r) for r in rows]}

    # ================= 证据中心 =================
    def list_evidence(
        self,
        document_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        """证据列表：显示所有抽取的证据片段。"""
        where = "WHERE e.document_id = ?" if document_id else ""
        params = (document_id,) if document_id else ()

        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) AS n FROM evidence e {where}",
                params
            ).fetchone()["n"]
        )

        rows = self.conn.execute(
            f"""
            SELECT e.evidence_id, e.document_id, e.snippet, e.page_number,
                   e.table_reference, e.locator, e.confidence, e.created_at,
                   d.content_kind, s.title as source_title,
                   COUNT(DISTINCT g.id) as record_count
            FROM evidence e
            LEFT JOIN documents d ON d.document_id = e.document_id
            LEFT JOIN sources s ON s.source_id = d.source_id
            LEFT JOIN generation_records g ON g.evidence_id = e.evidence_id
            {where}
            GROUP BY e.evidence_id
            ORDER BY e.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + (limit, offset)
        ).fetchall()

        return {"total": total, "items": [dict(r) for r in rows]}

    # ================= 设置 =================
    def get_system_info(self) -> dict[str, Any]:
        """系统信息：数据库大小、记录统计等。"""
        return {
            "database": {
                "stations": self._count("stations"),
                "projects": self._count("projects"),
                "sources": self._count("sources"),
                "documents": self._count("documents"),
                "evidence": self._count("evidence"),
                "records": self._count("generation_records"),
            },
            "storage": {
                "total_documents": self._count("documents"),
                "total_size_bytes": self.conn.execute(
                    "SELECT COALESCE(SUM(file_size), 0) as total FROM documents"
                ).fetchone()["total"]
            }
        }

    # ================= 项目管理 =================
    def list_projects(
        self,
        *,
        search: Optional[str] = None,
        country: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """项目列表（类似 list_stations）。"""
        where: list[str] = []
        params: list[Any] = []

        if search:
            where.append("(canonical_name LIKE ? OR aliases LIKE ?)")
            like = f"%{search}%"
            params += [like, like]
        if country:
            where.append("country = ?")
            params.append(country)
        if status:
            where.append("status = ?")
            params.append(status)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) AS n FROM projects{where_sql}", tuple(params)
            ).fetchone()["n"]
        )

        rows = self.conn.execute(
            f"""
            SELECT entity_id, canonical_name, country, state_province, river,
                   capacity_mw, status, operator, priority_tier
            FROM projects{where_sql}
            ORDER BY capacity_mw DESC NULLS LAST
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (limit, offset),
        ).fetchall()

        return {"total": total, "items": [dict(r) for r in rows]}

    # ================= 任务管理 =================
    def list_tasks(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        """采集任务列表。"""
        where = "WHERE t.status = ?" if status else ""
        params = (status,) if status else ()

        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) AS n FROM tasks t {where}", params
            ).fetchone()["n"]
        )

        rows = self.conn.execute(
            f"""
            SELECT t.task_id, t.entity_id, t.entity_type, t.task_type,
                   t.target_period, t.status, t.priority_tier,
                   t.failure_stage, t.last_error, t.source_type,
                   t.user_specified_source, t.attempts, t.max_attempts, t.created_at,
                   COALESCE(s.canonical_name, p.canonical_name) AS entity_name
            FROM tasks t
            LEFT JOIN stations s ON s.entity_id = t.entity_id AND t.entity_type = 'station'
            LEFT JOIN projects p ON p.entity_id = t.entity_id AND t.entity_type = 'project'
            {where}
            ORDER BY t.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + (limit, offset)
        ).fetchall()

        return {"total": total, "items": [dict(r) for r in rows]}

    def global_search(self, query: str) -> dict[str, Any]:
        """全局搜索：水电站、项目、来源。"""
        if not query or len(query) < 2:
            return {"stations": [], "projects": [], "sources": []}

        like = f"%{query}%"

        stations = [
            dict(r) for r in self.conn.execute(
                """
                SELECT entity_id, canonical_name AS name, country
                FROM stations
                WHERE canonical_name LIKE ? OR aliases LIKE ? OR country LIKE ?
                LIMIT 3
                """,
                (like, like, like)
            ).fetchall()
        ]

        projects = [
            dict(r) for r in self.conn.execute(
                """
                SELECT entity_id, canonical_name AS name, country
                FROM projects
                WHERE canonical_name LIKE ? OR aliases LIKE ?
                LIMIT 3
                """,
                (like, like)
            ).fetchall()
        ]

        sources = [
            dict(r) for r in self.conn.execute(
                """
                SELECT source_id, title, publisher
                FROM sources
                WHERE title LIKE ? OR publisher LIKE ?
                LIMIT 3
                """,
                (like, like)
            ).fetchall()
        ]

        return {"stations": stations, "projects": projects, "sources": sources}
