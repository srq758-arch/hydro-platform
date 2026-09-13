"""任务状态机单测：合法/非法转换、终态与允许目标集合。"""

from __future__ import annotations

import pytest

from hydro_platform.common.enums import TaskStatus
from hydro_platform.tasking.state_machine import (
    TERMINAL_STATES,
    IllegalTransition,
    allowed_targets,
    assert_transition,
    can_transition,
    is_terminal,
)

P = TaskStatus.PENDING
R = TaskStatus.RUNNING
S = TaskStatus.SUCCESS
F = TaskStatus.FAILED
N = TaskStatus.NEEDS_REVIEW
C = TaskStatus.CANCELLED

LEGAL = [
    (P, R),
    (P, C),
    (R, S),
    (R, F),
    (R, N),
    (R, C),
    (F, P),
    (F, C),
    (N, S),
    (N, F),
    (N, C),
]

ILLEGAL = [
    (P, S),
    (P, F),
    (P, N),
    (R, P),
    (S, P),
    (S, R),
    (S, F),
    (C, P),
    (C, R),
    (F, S),
    (F, R),
    (N, P),
    (N, R),
]


@pytest.mark.parametrize(("src", "dst"), LEGAL)
def test_legal_transitions(src, dst):
    assert can_transition(src, dst) is True
    assert_transition(src, dst)  # 不抛异常


@pytest.mark.parametrize(("src", "dst"), ILLEGAL)
def test_illegal_transitions(src, dst):
    assert can_transition(src, dst) is False
    with pytest.raises(IllegalTransition) as exc:
        assert_transition(src, dst)
    assert exc.value.src == src
    assert exc.value.dst == dst


def test_string_coercion():
    # DB 行里存的是裸字符串，状态机应能直接吃
    assert can_transition("pending", "running") is True
    assert_transition(TaskStatus.PENDING.value, TaskStatus.RUNNING.value)


def test_allowed_targets():
    assert allowed_targets(P) == frozenset({R, C})
    assert allowed_targets(R) == frozenset({S, F, N, C})
    assert allowed_targets(F) == frozenset({P, C})
    assert allowed_targets(N) == frozenset({S, F, C})
    assert allowed_targets(S) == frozenset()
    assert allowed_targets(C) == frozenset()


def test_terminal_states():
    assert TERMINAL_STATES == frozenset({S, C})
    assert is_terminal(S) is True
    assert is_terminal(C) is True
    assert is_terminal(P) is False
    assert is_terminal(R) is False
    assert is_terminal(F) is False
    assert is_terminal(N) is False
    # 字符串形式亦可
    assert is_terminal("success") is True
