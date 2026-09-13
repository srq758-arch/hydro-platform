"""Project Registry：新增项目注册表管理（任务 3.2）

职责：
- 加载项目种子数据
- 项目状态管理与历史跟踪
- 批量生成项目采集任务
- 按状态查询项目
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from ..common.clock import now_iso
from ..common.enums import EntityType, TaskType
from ..common.logging_setup import get_logger
from ..database.connection import transaction
from ..database.repositories import ProjectRepository
from ..models.project import Project

logger = get_logger(__name__)


class ProjectRegistry:
    """新增项目注册表：管理在建/新投产/规划中的水电项目。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = ProjectRepository(conn)

    def load_from_seed(self, seed_path: Path | None = None) -> int:
        """从 seed CSV 加载项目数据。返回加载行数。"""
        from .loader import load_projects
        return load_projects(self.conn, seed_path)

    def register_project(self, project: Project) -> str:
        """注册单个项目。返回 entity_id。"""
        with transaction(self.conn):
            self.repo.upsert_many([project])
        logger.info(f"注册项目：{project.entity_id} - {project.canonical_name}")
        return project.entity_id

    def update_project_status(
        self,
        project_id: str,
        new_status: str,
        effective_date: str | None = None,
        source_id: str | None = None,
        notes: str | None = None
    ) -> None:
        """更新项目状态并记录历史。

        Args:
            project_id: 项目 entity_id
            new_status: 新状态 (announced/approved/under_construction/newly_commissioned)
            effective_date: 生效日期（ISO格式）
            source_id: 来源ID
            notes: 备注信息

        状态枚举：
        - announced: 已宣布
        - approved: 已批准
        - under_construction: 在建
        - newly_commissioned: 新投产
        - operational: 已运营（转为正式电站）
        - cancelled: 已取消
        - suspended: 已暂停
        """
        # 验证项目存在
        project = self.repo.get(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")

        with transaction(self.conn):
            # 1. 记录状态变更历史
            self.conn.execute("""
                INSERT INTO project_status_history (
                    project_id, status, effective_date, source_id, notes, recorded_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (project_id, new_status, effective_date, source_id, notes, now_iso()))

            # 2. 更新 projects 表当前状态
            self.conn.execute("""
                UPDATE projects
                SET status = ?, updated_at = ?
                WHERE entity_id = ?
            """, (new_status, now_iso(), project_id))

        logger.info(f"项目 {project_id} 状态更新: {new_status}")

    def get_project(self, project_id: str) -> dict | None:
        """获取项目详情。"""
        row = self.repo.get(project_id)
        return dict(row) if row else None

    def get_status_history(self, project_id: str) -> list[dict]:
        """获取项目状态变更历史。"""
        rows = self.conn.execute("""
            SELECT
                psh.id,
                psh.project_id,
                psh.status,
                psh.effective_date,
                psh.recorded_at,
                psh.notes,
                s.title as source_title
            FROM project_status_history psh
            LEFT JOIN sources s ON s.source_id = psh.source_id
            WHERE psh.project_id = ?
            ORDER BY psh.recorded_at DESC
        """, (project_id,)).fetchall()
        return [dict(r) for r in rows]

    def query_projects_by_status(
        self,
        status: str | None = None,
        country: str | None = None,
        year_range: tuple[int, int] | None = None,
        limit: int | None = None
    ) -> list[dict]:
        """按条件查询项目。

        Args:
            status: 项目状态过滤
            country: 国家过滤
            year_range: 投产年份范围 (start_year, end_year)
            limit: 限制返回数量

        Returns:
            项目列表
        """
        query = "SELECT * FROM projects WHERE 1=1"
        params: list = []

        if status:
            query += " AND status = ?"
            params.append(status)

        if country:
            query += " AND country = ?"
            params.append(country)

        if year_range:
            start_year, end_year = year_range
            query += " AND commissioning_year BETWEEN ? AND ?"
            params.extend([start_year, end_year])

        query += " ORDER BY capacity_mw DESC NULLS LAST"

        if limit:
            query += f" LIMIT {int(limit)}"

        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def generate_project_tasks(
        self,
        status_filter: str | None = None,
        limit: int | None = None
    ) -> list[str]:
        """批量生成项目采集任务。

        Args:
            status_filter: 按状态过滤（under_construction/newly_commissioned等）
            limit: 限制生成数量

        Returns:
            task_ids: 创建的任务ID列表
        """
        from ..tasking.builder import build_project_tasks
        from ..database.repositories import TaskRepository

        # 查询符合条件的项目
        query = "SELECT entity_id, priority_tier, collection_priority FROM projects WHERE 1=1"
        params: list = []

        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)

        query += " ORDER BY priority_tier ASC, collection_priority ASC"

        if limit:
            query += f" LIMIT {int(limit)}"

        projects = self.conn.execute(query, params).fetchall()

        # 批量创建任务
        repo = TaskRepository(self.conn)
        all_tasks: list = []

        for row in projects:
            all_tasks.extend(build_project_tasks(row))

        with transaction(self.conn):
            written = repo.upsert_many(all_tasks)

        task_ids = [t.task_id for t in all_tasks]
        logger.info(f"批量生成项目任务 {written} 个（status={status_filter}, limit={limit}）")

        return task_ids

    def get_registry_stats(self) -> dict:
        """获取项目注册表统计信息。"""
        stats = {}

        # 项目总数和按状态统计
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN status = 'announced' THEN 1 END) as announced,
                COUNT(CASE WHEN status = 'approved' THEN 1 END) as approved,
                COUNT(CASE WHEN status = 'under_construction' THEN 1 END) as under_construction,
                COUNT(CASE WHEN status = 'newly_commissioned' THEN 1 END) as newly_commissioned,
                COUNT(CASE WHEN status = 'operational' THEN 1 END) as operational,
                SUM(capacity_mw) as total_capacity_mw
            FROM projects
        """).fetchone()
        stats['projects'] = dict(row)

        # 按国家统计
        rows = self.conn.execute("""
            SELECT country, COUNT(*) as count, SUM(capacity_mw) as capacity_mw
            FROM projects
            WHERE country IS NOT NULL
            GROUP BY country
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()
        stats['by_country'] = [dict(r) for r in rows]

        # 按年份统计
        rows = self.conn.execute("""
            SELECT commissioning_year, COUNT(*) as count
            FROM projects
            WHERE commissioning_year IS NOT NULL
            GROUP BY commissioning_year
            ORDER BY commissioning_year DESC
            LIMIT 10
        """).fetchall()
        stats['by_year'] = [dict(r) for r in rows]

        return stats

    def list_projects(
        self,
        offset: int = 0,
        limit: int = 50,
        order_by: str = 'capacity_mw'
    ) -> list[dict]:
        """列出项目（分页）。

        Args:
            offset: 偏移量
            limit: 每页数量
            order_by: 排序字段（capacity_mw/commissioning_year/canonical_name）

        Returns:
            项目列表
        """
        valid_order_fields = ['capacity_mw', 'commissioning_year', 'canonical_name', 'status']
        if order_by not in valid_order_fields:
            order_by = 'capacity_mw'

        query = f"""
            SELECT * FROM projects
            ORDER BY {order_by} DESC NULLS LAST
            LIMIT ? OFFSET ?
        """

        rows = self.conn.execute(query, (limit, offset)).fetchall()
        return [dict(r) for r in rows]
