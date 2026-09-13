"""通用结果类型。

Result：泛化的操作结果（成功/失败 + 数据 + 错误信息）。
ValidationResult：校验结果，禁止只返回 True/False（文档 13.2），必须携带
    问题列表、严重度和已检查字段，便于进入 Review Queue 时定位原因。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from .enums import Severity

T = TypeVar("T")


@dataclass
class Result(Generic[T]):
    """泛化操作结果。用 ok()/fail() 构造，避免裸抛异常打断批量流程。"""

    success: bool
    value: T | None = None
    error: str | None = None

    @classmethod
    def ok(cls, value: T | None = None) -> "Result[T]":
        return cls(success=True, value=value)

    @classmethod
    def fail(cls, error: str) -> "Result[T]":
        return cls(success=False, error=error)

    def __bool__(self) -> bool:
        return self.success


@dataclass
class ValidationIssue:
    """单条校验问题。code 取自文档 13.2 的问题码（如 YEAR_MISMATCH）。"""

    code: str
    message: str
    severity: Severity = Severity.MEDIUM
    field_name: str | None = None


@dataclass
class ValidationResult:
    """校验结果（文档 13.2）。

    passed 为整体结论；issues 为问题明细；checked_fields 记录检查过哪些字段，
    便于回溯「哪些校验真正执行过」。severity 取所有问题中的最高级别。
    """

    passed: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)
    checked_fields: list[str] = field(default_factory=list)

    @property
    def severity(self) -> Severity:
        """整体严重度 = 问题中的最高级别；无问题则为 low。"""
        order = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}
        if not self.issues:
            return Severity.LOW
        return max((i.severity for i in self.issues), key=lambda s: order[s])

    @property
    def has_blocking_issues(self) -> bool:
        """是否存在「硬阻断」问题（HIGH 级）。

        文档 13.3：区分「物理/逻辑上不可能」与「需人工确认」两类。
        HIGH 级（如量纲冲突、数值越界）是硬阻断，人工也不应直接放行；
        MEDIUM/LOW 级（如无法确认实际/预测）是复核触发项，人工核准后即可入库。
        promote 以本属性把关，而非 passed。
        """
        return any(i.severity is Severity.HIGH for i in self.issues)

    def add_issue(
        self,
        code: str,
        message: str,
        severity: Severity = Severity.MEDIUM,
        field_name: str | None = None,
    ) -> None:
        """追加一条问题，并将整体结论置为未通过。"""
        self.issues.append(ValidationIssue(code, message, severity, field_name))
        self.passed = False
