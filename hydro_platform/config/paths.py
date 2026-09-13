"""运行时路径管理（文档 19 目录布局）。

集中定义所有目录/文件路径，任何模块不得硬编码相对路径。
项目根通过本文件位置反推（config/paths.py -> 上两级），可被环境变量
HYDRO_DATA_DIR 覆盖数据根，便于测试隔离与多环境部署。

V1 支持两种数据目录模式：
1. 开发模式：使用项目内 data/ 目录
2. 生产模式：使用 %LOCALAPPDATA%/HydropowerData/（文档第 2.1 节）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 项目根：本文件在 <root>/hydro_platform/config/paths.py，向上三级即根。
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


def get_user_data_dir(mode: str = "production") -> Path:
    """获取用户数据目录（文档第 10.1 节要求）。

    生产环境：%LOCALAPPDATA%/HydropowerData/
    开发环境：<project_root>/data/
    """
    if mode not in {"production", "test"}:
        raise ValueError("mode must be production or test")
    if mode == "test":
        return data_root() / "test"

    # 检查是否为打包后的 exe（PyInstaller）
    if getattr(sys, 'frozen', False):
        # 打包环境：使用 Windows LOCALAPPDATA
        local_app_data = os.environ.get('LOCALAPPDATA')
        if local_app_data:
            return Path(local_app_data) / "HydropowerData"

    # 开发环境：使用项目内 data/ 目录
    return data_root()


def data_root() -> Path:
    """数据根目录。默认 <root>/data，可用 HYDRO_DATA_DIR 覆盖（测试隔离用）。"""
    env = os.environ.get("HYDRO_DATA_DIR")
    return Path(env).resolve() if env else PROJECT_ROOT / "data"


def seed_dir() -> Path:
    """GEM seed 数据目录（station/project seed list 所在处）。"""
    return data_root() / "seed"


def station_seed_csv() -> Path:
    return seed_dir() / "station_seed_list.csv"


def project_seed_csv() -> Path:
    return seed_dir() / "project_seed_list.csv"


def db_dir() -> Path:
    """SQLite 数据库目录。"""
    return data_root() / "db"


def db_path() -> Path:
    """主数据库文件路径。"""
    return db_dir() / "hydro.db"


def get_database_path(mode: str = "production") -> Path:
    """获取数据库路径；test 模式使用完全隔离的 hydro_test.db。"""
    return get_user_data_dir(mode) / "db" / ("hydro_test.db" if mode == "test" else "hydro.db")


def archive_dir() -> Path:
    """原始快照归档根目录（文档 8 Acquisition/Archive 层，后续阶段使用）。"""
    return data_root() / "archive"


def raw_dir() -> Path:
    """原始资料落盘目录（文档 10.1 raw/）。Archive 层写入原始字节。"""
    return data_root() / "raw"


def parsed_dir() -> Path:
    """解析产物目录（文档 10.1 parsed/）。"""
    return data_root() / "parsed"


def export_dir() -> Path:
    """产品层导出目录（Top 100 等，后续阶段使用）。"""
    return data_root() / "export"


def ensure_runtime_dirs() -> None:
    """确保运行期需要写入的目录存在（幂等）。"""
    for d in (data_root(), db_dir(), archive_dir(), raw_dir(), parsed_dir(), export_dir()):
        d.mkdir(parents=True, exist_ok=True)
