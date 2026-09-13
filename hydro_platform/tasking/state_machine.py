"""任务状态机（文档 5.3）。

只定义「哪些状态转换合法」，不碰持久化——执行与落库由 tasking.manager 负责。
把规则集中在这里，避免各处用裸字符串自行判断导致状态漂移。

合法转换图：

    pending ──▶ running ──▶ success
       │          │
       │          ├──▶ failed ──▶ pending   （重试：requeue）
       │          │
       │          ├──▶ needs_review ──▶ success   （人工 approve）
       │          │                └──▶ failed    （人工 reject）
       │          │
       ▼          ▼
    cancelled  cancelled

success / cancelled 为终态，不再转出。
"""

from __future__ import annotations

from ..common.enums import TaskStatus

# 每个状态 → 允许转入的状态集合
_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.NEEDS_REVIEW,
        TaskStatus.CANCELLED,
    }),
    # 失败后可重新排队（requeue）等待下一轮调度；也可直接取消
    TaskStatus.FAILED: frozenset({TaskStatus.PENDING, TaskStatus.CANCELLED}),
    # 复核结论：通过 → success，驳回 → failed，也可取消
    TaskStatus.NEEDS_REVIEW: frozenset({
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }),
    TaskStatus.SUCCESS: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

# 终态：不再参与调度
TERMINAL_STATES: frozenset[TaskStatus] = frozenset({
    TaskStatus.SUCCESS,
    TaskStatus.CANCELLED,
})


class IllegalTransition(ValueError):
    """非法状态转换。"""

    def __init__(self, src: TaskStatus, dst: TaskStatus) -> None:
        super().__init__(f"非法状态转换：{src.value} → {dst.value}")
        self.src = src
        self.dst = dst


def _coerce(status: TaskStatus | str) -> TaskStatus:
    """把裸字符串归一为 TaskStatus，便于从 DB 行直接传入。"""
    return status if isinstance(status, TaskStatus) else TaskStatus(status)


def allowed_targets(src: TaskStatus | str) -> frozenset[TaskStatus]:
    """返回 src 状态允许转入的目标集合。"""
    return _TRANSITIONS[_coerce(src)]


def can_transition(src: TaskStatus | str, dst: TaskStatus | str) -> bool:
    """判断 src → dst 是否合法。"""
    return _coerce(dst) in _TRANSITIONS[_coerce(src)]


def assert_transition(src: TaskStatus | str, dst: TaskStatus | str) -> None:
    """校验转换合法，否则抛 IllegalTransition。"""
    s, d = _coerce(src), _coerce(dst)
    if d not in _TRANSITIONS[s]:
        raise IllegalTransition(s, d)


def is_terminal(status: TaskStatus | str) -> bool:
    """是否终态。"""
    return _coerce(status) in TERMINAL_STATES
