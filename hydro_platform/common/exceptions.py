"""系统自定义异常层级。

所有业务异常继承 HydroError，便于上层统一捕获并转成失败分类（FailureStage）。
"""

from __future__ import annotations


class HydroError(Exception):
    """系统根异常。"""


class ConfigError(HydroError):
    """配置缺失或非法。"""


class DatabaseError(HydroError):
    """数据库连接、迁移或写入失败。"""


class MigrationError(DatabaseError):
    """迁移执行失败（版本冲突、DDL 错误等）。"""


class RegistryError(HydroError):
    """Registry 加载或映射失败（seed 文件缺失、列缺失等）。"""


class InvalidStateTransition(HydroError):
    """非法任务状态转换（由 tasking.state_machine 抛出）。"""

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"非法状态转换：{current} -> {target}")
