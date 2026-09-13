"""端到端集成：seed CSV → registry loader → SQLite，含幂等重跑验收。

用小型内联 seed 子集，不读真实 4965/2058 行大文件，保持快速与确定性。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydro_platform.database.repositories import (
    ProjectRepository,
    RegistryAuditRepository,
    StationRepository,
)
from hydro_platform.registry import loader

# 与真实 seed 同构的最小列集（含 BOM 触发列、turbines 配置串、needs_review）
_HEADER = (
    "entity_id,entity_type,canonical_name,country,capacity_mw,turbines,"
    "commissioning_year,retired_year,priority_tier,collection_priority,"
    "needs_review,registry_version,raw_record_hash"
)
_STATION_ROWS = [
    "st-1,station,Alpha Dam,CN,22500,32 x 700 MW; 2 x 50 MW,2003,,T1,1,0,v2024,h1",
    "st-2,station,Beta Dam,BR,14000,20,1984,,T1,2,0,v2024,h2",
    "st-3,station,Gamma Dam,US,,,,1998,T3,9,1,v2024,h3",
]
_PROJECT_ROWS = [
    "pj-1,project,Delta Project,IN,1200,4 x 300 MW,,,T2,3,0,v2024,p1",
    "pj-2,project,Epsilon Project,ET,6450,13 x 500 MW,,,T1,1,0,v2024,p2",
]


def _write_csv(path: Path, rows: list[str]) -> None:
    # 带 UTF-8 BOM，验证 loader 的 utf-8-sig 处理
    path.write_text("﻿" + _HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture()
def seed_dir(tmp_path: Path) -> Path:
    d = tmp_path / "seed"
    d.mkdir()
    _write_csv(d / "station_seed_list.csv", _STATION_ROWS)
    _write_csv(d / "project_seed_list.csv", _PROJECT_ROWS)
    return d


def test_seed_to_db_end_to_end(db, seed_dir):
    ns = loader.load_stations(db, seed_dir / "station_seed_list.csv")
    npj = loader.load_projects(db, seed_dir / "project_seed_list.csv")
    assert (ns, npj) == (3, 2)

    stations = StationRepository(db)
    projects = ProjectRepository(db)
    assert stations.count() == 3
    assert projects.count() == 2

    # turbines 配置串求和：32+2=34
    assert stations.get("st-1")["turbines"] == 34
    assert stations.get("st-2")["turbines"] == 20
    # 空 capacity/turbines 归 None
    assert stations.get("st-3")["capacity_mw"] is None
    assert stations.get("st-3")["turbines"] is None
    # needs_review 布尔落 0/1
    assert stations.get("st-3")["needs_review"] == 1
    # retired_year 仅 station 带入
    assert stations.get("st-3")["retired_year"] == 1998

    # 每次导入一条 audit
    assert RegistryAuditRepository(db).count() == 2


def test_rerun_is_idempotent(db, seed_dir):
    loader.load_stations(db, seed_dir / "station_seed_list.csv")
    loader.load_projects(db, seed_dir / "project_seed_list.csv")
    # 重跑：实体行数不变（幂等验收核心）
    loader.load_stations(db, seed_dir / "station_seed_list.csv")
    loader.load_projects(db, seed_dir / "project_seed_list.csv")

    assert StationRepository(db).count() == 3
    assert ProjectRepository(db).count() == 2
    # audit 是留痕表，每次导入追加：4 次导入 = 4 条
    assert RegistryAuditRepository(db).count() == 4
