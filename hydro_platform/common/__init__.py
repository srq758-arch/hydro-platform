"""通用基础设施：枚举、结果类型、异常、日志、时间源。"""

from .enums import (
    AccessMethod,
    AcquisitionErrorCode,
    ContentKind,
    FailureStage,
    TaskStatus,
    ValueType,
    MeasurementScope,
)
from .exceptions import HydroError
from .result import Result

__all__ = [
    "AccessMethod",
    "AcquisitionErrorCode",
    "ContentKind",
    "FailureStage",
    "TaskStatus",
    "ValueType",
    "MeasurementScope",
    "HydroError",
    "Result",
]
