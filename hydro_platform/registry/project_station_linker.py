"""Project-Station Linking：项目与电站关联机制（任务 3.3）

职责：
- 手动建立项目-电站关联
- 查询电站的建设项目历史
- 查询项目对应的电站
- 自动关联（按名称+年份匹配）
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from ..common.clock import now_iso
from ..common.logging_setup import get_logger
from ..database.connection import transaction

logger = get_logger(__name__)


class ProjectStationLinker:
    """项目-电站关联管理器。

    link_type 类型：
    - commissioning: 新建投产（项目完成后成为新电站）
    - expansion: 扩建（项目为现有电站增加容量/机组）
    - upgrade: 改造升级（技术改造、设备更新）
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def link_on_commissioning(
        self,
        project_id: str,
        station_id: str,
        commissioning_date: str | None = None,
        source_id: str | None = None,
        confidence: float = 1.0,
        notes: str | None = None
    ) -> int:
        """建立投产关联：项目完成后成为电站。

        Args:
            project_id: 项目 entity_id
            station_id: 电站 entity_id
            commissioning_date: 投产日期（ISO格式）
            source_id: 来源ID
            confidence: 置信度 (0.0-1.0)
            notes: 备注信息

        Returns:
            link_id: 关联记录ID
        """
        return self._create_link(
            project_id=project_id,
            station_id=station_id,
            link_type='commissioning',
            effective_date=commissioning_date,
            source_id=source_id,
            confidence=confidence,
            notes=notes
        )

    def link_on_expansion(
        self,
        project_id: str,
        station_id: str,
        expansion_date: str | None = None,
        source_id: str | None = None,
        confidence: float = 1.0,
        notes: str | None = None
    ) -> int:
        """建立扩建关联：项目为现有电站增加容量。

        Args:
            project_id: 扩建项目 entity_id
            station_id: 现有电站 entity_id
            expansion_date: 扩建完成日期
            source_id: 来源ID
            confidence: 置信度
            notes: 备注（如：增加XXX MW容量）

        Returns:
            link_id: 关联记录ID
        """
        return self._create_link(
            project_id=project_id,
            station_id=station_id,
            link_type='expansion',
            effective_date=expansion_date,
            source_id=source_id,
            confidence=confidence,
            notes=notes
        )

    def link_on_upgrade(
        self,
        project_id: str,
        station_id: str,
        upgrade_date: str | None = None,
        source_id: str | None = None,
        confidence: float = 1.0,
        notes: str | None = None
    ) -> int:
        """建立改造关联：项目对现有电站进行技术升级。

        Args:
            project_id: 改造项目 entity_id
            station_id: 电站 entity_id
            upgrade_date: 改造完成日期
            source_id: 来源ID
            confidence: 置信度
            notes: 备注（如：机组更新、效率提升）

        Returns:
            link_id: 关联记录ID
        """
        return self._create_link(
            project_id=project_id,
            station_id=station_id,
            link_type='upgrade',
            effective_date=upgrade_date,
            source_id=source_id,
            confidence=confidence,
            notes=notes
        )

    def _create_link(
        self,
        project_id: str,
        station_id: str,
        link_type: str,
        effective_date: str | None,
        source_id: str | None,
        confidence: float,
        notes: str | None
    ) -> int:
        """内部方法：创建关联记录。"""
        with transaction(self.conn):
            cursor = self.conn.execute("""
                INSERT INTO project_station_links (
                    project_id, station_id, link_type, effective_date,
                    confidence_score, source_id, notes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, station_id, link_type) DO UPDATE SET
                    effective_date = excluded.effective_date,
                    confidence_score = excluded.confidence_score,
                    source_id = excluded.source_id,
                    notes = excluded.notes
            """, (
                project_id, station_id, link_type, effective_date,
                confidence, source_id, notes, now_iso()
            ))

            link_id = cursor.lastrowid

        logger.info(f"项目-电站关联: {project_id} -> {station_id} ({link_type})")
        return link_id

    def get_station_projects(self, station_id: str) -> list[dict]:
        """查询电站的建设项目历史（投产/扩建/改造）。

        Args:
            station_id: 电站 entity_id

        Returns:
            项目列表（含关联类型和日期）
        """
        query = """
            SELECT
                p.entity_id,
                p.canonical_name,
                p.status,
                p.capacity_mw,
                p.commissioning_year,
                l.link_type,
                l.effective_date,
                l.confidence_score,
                l.notes,
                l.created_at
            FROM project_station_links l
            JOIN projects p ON l.project_id = p.entity_id
            WHERE l.station_id = ?
            ORDER BY l.effective_date DESC NULLS LAST, l.created_at DESC
        """
        rows = self.conn.execute(query, (station_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_project_stations(self, project_id: str) -> list[dict]:
        """查询项目关联的电站（一个项目可能对应多个电站/机组）。

        Args:
            project_id: 项目 entity_id

        Returns:
            电站列表（含关联类型和日期）
        """
        query = """
            SELECT
                s.entity_id,
                s.canonical_name,
                s.country,
                s.capacity_mw,
                l.link_type,
                l.effective_date,
                l.confidence_score,
                l.notes,
                l.created_at
            FROM project_station_links l
            JOIN stations s ON l.station_id = s.entity_id
            WHERE l.project_id = ?
            ORDER BY l.effective_date DESC NULLS LAST
        """
        rows = self.conn.execute(query, (project_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_link(
        self,
        project_id: str,
        station_id: str,
        link_type: str | None = None
    ) -> dict | None:
        """获取特定关联记录。

        Args:
            project_id: 项目 entity_id
            station_id: 电站 entity_id
            link_type: 关联类型（可选）

        Returns:
            关联记录，不存在返回 None
        """
        if link_type:
            query = """
                SELECT * FROM project_station_links
                WHERE project_id = ? AND station_id = ? AND link_type = ?
            """
            row = self.conn.execute(query, (project_id, station_id, link_type)).fetchone()
        else:
            query = """
                SELECT * FROM project_station_links
                WHERE project_id = ? AND station_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """
            row = self.conn.execute(query, (project_id, station_id)).fetchone()

        return dict(row) if row else None

    def remove_link(
        self,
        project_id: str,
        station_id: str,
        link_type: str | None = None
    ) -> int:
        """删除关联记录。

        Args:
            project_id: 项目 entity_id
            station_id: 电站 entity_id
            link_type: 关联类型（可选，不指定则删除所有类型）

        Returns:
            删除的记录数
        """
        with transaction(self.conn):
            if link_type:
                cursor = self.conn.execute("""
                    DELETE FROM project_station_links
                    WHERE project_id = ? AND station_id = ? AND link_type = ?
                """, (project_id, station_id, link_type))
            else:
                cursor = self.conn.execute("""
                    DELETE FROM project_station_links
                    WHERE project_id = ? AND station_id = ?
                """, (project_id, station_id))

            deleted = cursor.rowcount

        logger.info(f"删除关联: {project_id} -> {station_id}, 删除 {deleted} 条")
        return deleted

    def auto_link_by_name_and_year(
        self,
        confidence_threshold: float = 0.8,
        dry_run: bool = False
    ) -> list[tuple]:
        """自动关联：按名称相似度和投产年份匹配。

        匹配规则：
        1. canonical_name 完全匹配（不区分大小写）
        2. commissioning_year 一致
        3. 尚未建立关联

        Args:
            confidence_threshold: 置信度阈值（当前简化实现固定为1.0）
            dry_run: 是否仅预览而不实际创建关联

        Returns:
            匹配列表 [(project_id, station_id, confidence), ...]
        """
        query = """
            SELECT
                p.entity_id AS project_id,
                s.entity_id AS station_id,
                p.canonical_name AS project_name,
                s.canonical_name AS station_name,
                p.commissioning_year,
                1.0 AS confidence
            FROM projects p
            JOIN stations s ON (
                LOWER(TRIM(p.canonical_name)) = LOWER(TRIM(s.canonical_name))
                AND p.commissioning_year IS NOT NULL
                AND s.commissioning_year IS NOT NULL
                AND p.commissioning_year = s.commissioning_year
            )
            WHERE NOT EXISTS (
                SELECT 1 FROM project_station_links l
                WHERE l.project_id = p.entity_id AND l.station_id = s.entity_id
            )
        """
        matches = self.conn.execute(query).fetchall()

        results = []
        for match in matches:
            results.append((
                match['project_id'],
                match['station_id'],
                match['confidence']
            ))

            if not dry_run:
                # 实际创建关联
                self.link_on_commissioning(
                    project_id=match['project_id'],
                    station_id=match['station_id'],
                    commissioning_date=f"{match['commissioning_year']}-01-01",
                    confidence=match['confidence'],
                    notes=f"自动关联：名称匹配 ({match['project_name']})"
                )

        logger.info(f"自动关联完成: {len(results)} 对匹配 (dry_run={dry_run})")
        return results

    def get_link_stats(self) -> dict:
        """获取关联统计信息。"""
        stats = {}

        # 总关联数
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN link_type = 'commissioning' THEN 1 END) as commissioning,
                COUNT(CASE WHEN link_type = 'expansion' THEN 1 END) as expansion,
                COUNT(CASE WHEN link_type = 'upgrade' THEN 1 END) as upgrade
            FROM project_station_links
        """).fetchone()
        stats['links'] = dict(row)

        # 有关联的项目数
        row = self.conn.execute("""
            SELECT COUNT(DISTINCT project_id) as count
            FROM project_station_links
        """).fetchone()
        stats['linked_projects'] = row['count']

        # 有关联的电站数
        row = self.conn.execute("""
            SELECT COUNT(DISTINCT station_id) as count
            FROM project_station_links
        """).fetchone()
        stats['linked_stations'] = row['count']

        return stats
