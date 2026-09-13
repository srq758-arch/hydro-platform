"""Seed 加载器：读 GEM seed CSV → 领域模型 → upsert 入库（文档 6 / 23.1）。

只做「加载存量电站 + 新增项目」两件事，幂等：以 entity_id 为主键 upsert，
重复导入同一 seed 不新增行。每次导入在 registry_audit 留一条批次痕迹。

CSV 列多于模型字段（seed 含 gem_row_type/city/complex_name 等），只映射
模型定义的子集；空串一律归 None，交由 Pydantic 做字段级校验。
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Callable, Iterator

from ..common.logging_setup import get_logger
from ..config import paths
from ..database.connection import transaction
from ..database.repositories import (
    ProjectRepository,
    RegistryAuditRepository,
    StationRepository,
)
from ..models.project import Project
from ..models.station import Station

logger = get_logger(__name__)

# 模型共有的字符串字段（空串 -> None，原样传入）
_STR_FIELDS = (
    "entity_id", "entity_type", "canonical_name", "aliases", "local_name",
    "country", "country_2", "region", "subregion", "state_province", "river",
    "location_accuracy", "status", "technology", "operator", "owner",
    "gem_location_id", "gem_unit_id", "gem_wiki_url", "priority_tier",
    "source_seed", "source_url", "dataset_version", "registry_version",
    "raw_record_hash",
)
_FLOAT_FIELDS = ("latitude", "longitude", "capacity_mw")
_INT_FIELDS = ("commissioning_year", "collection_priority")
# retired_year 仅 Station 有；映射时按目标模型字段存在性决定是否带入
_STATION_ONLY_INT = ("retired_year",)


def _clean(v: str | None) -> str | None:
    """空串/纯空白 -> None，其余去首尾空白。"""
    if v is None:
        return None
    s = v.strip()
    return s or None


def _to_float(v: str | None) -> float | None:
    s = _clean(v)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        logger.warning("无法解析为 float，置空：%r", v)
        return None


def _to_int(v: str | None) -> int | None:
    s = _clean(v)
    if s is None:
        return None
    try:
        # 兼容 "1990.0" 之类写法
        return int(float(s))
    except ValueError:
        logger.warning("无法解析为 int，置空：%r", v)
        return None


def _parse_turbines(v: str | None) -> int | None:
    """解析 seed 的 turbines 列。

    该列混用两种写法：纯整数（"20"）或机组配置串（"32 x 700 MW; 2 x 50 MW"）。
    配置串按 ';' 分段，取每段 'N x ...' 的前导倍数 N 求和得总机组数（32+2=34）。
    无法解析则置空并 warning。
    """
    s = _clean(v)
    if s is None:
        return None
    if s.isdigit():
        return int(s)
    total = 0
    matched = False
    for seg in s.split(";"):
        head = seg.strip().lower().split("x", 1)[0].strip()
        if head.isdigit():
            total += int(head)
            matched = True
    if matched:
        return total
    logger.warning("无法解析 turbines，置空：%r", v)
    return None


def _to_bool(v: str | None) -> bool:
    s = _clean(v)
    if s is None:
        return False
    return s.lower() in ("1", "true", "yes", "y", "t")


def _row_to_kwargs(row: dict[str, str], *, include_retired: bool) -> dict:
    """把一行 CSV 映射为模型构造参数（只取模型认识的字段）。"""
    kwargs: dict = {}
    for f in _STR_FIELDS:
        if f in row:
            kwargs[f] = _clean(row.get(f))
    for f in _FLOAT_FIELDS:
        if f in row:
            kwargs[f] = _to_float(row.get(f))
    for f in _INT_FIELDS:
        if f in row:
            kwargs[f] = _to_int(row.get(f))
    if "turbines" in row:
        kwargs["turbines"] = _parse_turbines(row.get("turbines"))
    if include_retired and "retired_year" in row:
        kwargs["retired_year"] = _to_int(row.get("retired_year"))
    kwargs["needs_review"] = _to_bool(row.get("needs_review"))
    # entity_type 交给模型默认值兜底（seed 可能为空）
    if not kwargs.get("entity_type"):
        kwargs.pop("entity_type", None)
    return kwargs


def _iter_rows(csv_path: Path) -> Iterator[dict[str, str]]:
    """按行产出 CSV 字典。utf-8-sig 吞掉 BOM。"""
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        yield from csv.DictReader(fh)


def _load_entities(
    csv_path: Path,
    *,
    model_cls: Callable,
    include_retired: bool,
) -> tuple[list, str | None]:
    """解析 CSV 为模型列表。返回 (models, registry_version)。

    registry_version 取首行的值（同一 seed 批次内一致）。校验失败的行记 warning
    并跳过，不中断整批导入。
    """
    models: list = []
    registry_version: str | None = None
    for i, row in enumerate(_iter_rows(csv_path)):
        if registry_version is None:
            registry_version = _clean(row.get("registry_version"))
        try:
            models.append(model_cls(**_row_to_kwargs(row, include_retired=include_retired)))
        except Exception as exc:  # pydantic ValidationError 等
            logger.warning("第 %d 行校验失败，跳过：%s", i + 2, exc)
    return models, registry_version


def load_stations(conn: sqlite3.Connection, csv_path: Path | None = None) -> int:
    """加载存量电站 seed → stations 表。返回 upsert 行数。"""
    path = csv_path or paths.station_seed_csv()
    stations, version = _load_entities(path, model_cls=Station, include_retired=True)
    with transaction(conn):
        n = StationRepository(conn).upsert_many(stations)
        RegistryAuditRepository(conn).record(
            registry_kind="station",
            registry_version=version,
            row_count=n,
            source_file=str(path),
        )
    logger.info("加载存量电站 %d 条（registry_version=%s）", n, version)
    return n


def load_projects(conn: sqlite3.Connection, csv_path: Path | None = None) -> int:
    """加载新增项目 seed → projects 表。返回 upsert 行数。"""
    path = csv_path or paths.project_seed_csv()
    projects, version = _load_entities(path, model_cls=Project, include_retired=False)
    with transaction(conn):
        n = ProjectRepository(conn).upsert_many(projects)
        RegistryAuditRepository(conn).record(
            registry_kind="project",
            registry_version=version,
            row_count=n,
            source_file=str(path),
        )
    logger.info("加载新增项目 %d 条（registry_version=%s）", n, version)
    return n


def load_all(conn: sqlite3.Connection) -> tuple[int, int]:
    """加载两类 seed。返回 (stations, projects) 行数。"""
    return load_stations(conn), load_projects(conn)


# ==================== Master Registry 批量任务生成 ====================

class MasterRegistry:
    """Master Registry：存量电站主名单管理 + 批量任务生成（任务 3.1）。

    职责：
    - 加载电站/项目 seed
    - 批量生成采集任务
    - 按名称/别名查询实体
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def load_from_seed(self, station_csv: Path | None = None, project_csv: Path | None = None) -> tuple[int, int]:
        """从 seed CSV 加载电站和项目。返回 (stations, projects) 行数。"""
        return load_all(self.conn)

    def generate_batch_tasks(
        self,
        metric: str = 'generation',
        target_years: list[int] | None = None,
        priority_tier: str | None = None,
        limit: int | None = None
    ) -> list[str]:
        """批量生成采集任务。

        Args:
            metric: 指标类型 ('generation' / 'capacity')
            target_years: 目标年份列表，默认 [2023]
            priority_tier: 优先级过滤 (None=全部, 'A'=Top100相关, 'B'=中等, 'C'=低)
            limit: 限制生成数量

        Returns:
            task_ids: 创建的任务ID列表
        """
        from ..tasking.builder import build_station_tasks, _mk_task
        from ..database.repositories import TaskRepository
        from ..common.enums import EntityType, TaskType

        if target_years is None:
            target_years = [2023]

        # 查询符合条件的电站
        query = "SELECT entity_id, priority_tier, collection_priority FROM stations WHERE 1=1"
        params: list = []

        if priority_tier:
            query += " AND priority_tier = ?"
            params.append(priority_tier)

        query += " ORDER BY priority_tier ASC, collection_priority ASC"

        if limit:
            query += f" LIMIT {int(limit)}"

        stations = self.conn.execute(query, params).fetchall()

        # 批量创建任务
        repo = TaskRepository(self.conn)
        all_tasks: list = []

        if metric == 'generation':
            # 生成发电量任务
            for row in stations:
                all_tasks.extend(build_station_tasks(row, years=target_years))
        elif metric == 'capacity':
            # 仅生成容量任务
            for row in stations:
                all_tasks.append(_mk_task(
                    entity_id=row['entity_id'],
                    entity_type=EntityType.STATION,
                    task_type=TaskType.STATION_CAPACITY,
                    target_period=None,
                    priority_tier=row['priority_tier'],
                    collection_priority=row['collection_priority']
                ))
        else:
            raise ValueError(f"未知的metric类型: {metric}")

        with transaction(self.conn):
            written = repo.upsert_many(all_tasks)

        task_ids = [t.task_id for t in all_tasks]
        logger.info(f"批量生成 {written} 个任务（metric={metric}, years={target_years}, priority={priority_tier}, limit={limit}）")

        return task_ids

    def get_entity_by_name(self, name: str, fuzzy: bool = False) -> dict | None:
        """按名称查询电站（支持别名模糊匹配）。

        Args:
            name: 电站名称
            fuzzy: 是否启用模糊匹配（匹配 canonical_name 或 aliases）

        Returns:
            电站记录字典，未找到返回 None
        """
        if fuzzy:
            # 模糊匹配：canonical_name 或 aliases
            query = """
                SELECT * FROM stations
                WHERE canonical_name LIKE ?
                OR aliases LIKE ?
                LIMIT 1
            """
            pattern = f"%{name}%"
            row = self.conn.execute(query, (pattern, pattern)).fetchone()
        else:
            # 精确匹配
            query = "SELECT * FROM stations WHERE canonical_name = ? LIMIT 1"
            row = self.conn.execute(query, (name,)).fetchone()

        return dict(row) if row else None

    def get_registry_stats(self) -> dict:
        """获取注册表统计信息。"""
        stats = {}

        # 电站统计
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN priority_tier = 'A' THEN 1 END) as tier_a,
                COUNT(CASE WHEN priority_tier = 'B' THEN 1 END) as tier_b,
                COUNT(CASE WHEN priority_tier = 'C' THEN 1 END) as tier_c,
                SUM(capacity_mw) as total_capacity_mw
            FROM stations
        """).fetchone()
        stats['stations'] = dict(row)

        # 项目统计
        row = self.conn.execute("SELECT COUNT(*) as total FROM projects").fetchone()
        stats['projects'] = {'total': row['total']}

        # 任务统计
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                COUNT(CASE WHEN status = 'running' THEN 1 END) as running,
                COUNT(CASE WHEN status = 'done' THEN 1 END) as done,
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
            FROM tasks
        """).fetchone()
        stats['tasks'] = dict(row)

        return stats
