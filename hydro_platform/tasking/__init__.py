"""任务系统：状态机、批量 Task 生成器与任务管理器。"""

from .builder import (
    build_project_tasks,
    build_station_tasks,
    generate_from_registry,
)
from .manager import TaskManager, TaskNotFound
from .state_machine import (
    TERMINAL_STATES,
    IllegalTransition,
    allowed_targets,
    assert_transition,
    can_transition,
    is_terminal,
)

__all__ = [
    "build_project_tasks",
    "build_station_tasks",
    "generate_from_registry",
    "TaskManager",
    "TaskNotFound",
    "TERMINAL_STATES",
    "IllegalTransition",
    "allowed_targets",
    "assert_transition",
    "can_transition",
    "is_terminal",
]
