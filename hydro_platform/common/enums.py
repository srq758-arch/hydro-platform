"""全系统枚举定义。

集中管理，避免各模块用裸字符串导致口径漂移。字段值对齐设计文档
docs/hydro_platform_v1_final_framework.md 第 5、13、16、17 节。
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """字符串枚举基类：成员既是 Enum 又是 str，便于直接写入 SQLite / JSON。"""

    def __str__(self) -> str:  # pragma: no cover - 简单转换
        return self.value


class EntityType(StrEnum):
    """实体类型：存量电站 / 新增项目。"""

    STATION = "station"
    PROJECT = "project"
    UNKNOWN = "unknown"


class TaskType(StrEnum):
    """统一任务类型（文档 5.2）。"""

    STATION_GENERATION = "station_generation"
    STATION_CAPACITY = "station_capacity"
    PROJECT_STATUS = "project_status"
    PROJECT_COMMISSIONING = "project_commissioning"
    USER_QUERY = "user_query"


class TaskStatus(StrEnum):
    """任务状态（文档 5.3）。合法转换由 tasking.state_machine 约束。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"


class PeriodType(StrEnum):
    """统计周期类型（文档 5.1 period_type）。"""

    CALENDAR_YEAR = "calendar_year"
    FISCAL_YEAR = "fiscal_year"
    QUARTER = "quarter"


class ValueType(StrEnum):
    """数值性质：实际 / 预测 / 估算（文档 16.2 value_type）。

    区分 actual/forecast 是防止「预测值冒充实际值」的关键（文档 12.3）。
    """

    ACTUAL = "actual"
    FORECAST = "forecast"
    ESTIMATE = "estimate"


class MeasurementScope(StrEnum):
    """测量范围：单站 / 电站群 / 区域（文档 16.2 measurement_scope）。

    区分 plant/complex/region 是防止「区域合计冒充单站数据」的关键（文档 12.3）。
    """

    PLANT = "plant"
    COMPLEX = "complex"
    REGION = "region"


class ProjectStatus(StrEnum):
    """新增项目状态（文档 3.2）。"""

    NEWLY_COMMISSIONED = "newly_commissioned"
    UNDER_CONSTRUCTION = "under_construction"
    APPROVED = "approved"
    ANNOUNCED = "announced"


class Severity(StrEnum):
    """校验问题严重度（文档 13.2 severity）。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewDecision(StrEnum):
    """人工复核决策（文档 15）。"""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"


class PublicationStatus(StrEnum):
    """发布状态。只有 publishable 记录才能进入 Top 100（文档 15 / 20.1）。"""

    DRAFT = "draft"
    PUBLISHABLE = "publishable"
    WITHHELD = "withheld"


class FailureStage(StrEnum):
    """失败分类：记录管线在哪个阶段因何失败（文档 17.4）。"""

    DISCOVERY_FAILED = "DISCOVERY_FAILED"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    ACQUISITION_FAILED = "ACQUISITION_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    EXTRACTION_EMPTY = "EXTRACTION_EMPTY"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    DATABASE_WRITE_FAILED = "DATABASE_WRITE_FAILED"


class AccessMethod(StrEnum):
    """采集访问方式（文档 9.1 路由）。"""

    HTTP = "http"
    API = "api"
    BROWSER = "browser"
    LOCAL_IMPORT = "local_import"  # 本地文件手动导入


class ContentKind(StrEnum):
    """期望/识别到的内容类型（文档 9.2 / 9.4 / 11）。"""

    PDF = "pdf"
    EXCEL = "excel"
    CSV = "csv"
    JSON = "json"
    HTML = "html"
    UNKNOWN = "unknown"
    ANY = "any"


class AcquisitionErrorCode(StrEnum):
    """下载失败/不合法分类（文档 9.4 错误分类示例）。"""

    NETWORK_ERROR = "NETWORK_ERROR"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    READ_TIMEOUT = "READ_TIMEOUT"
    HTTP_403 = "HTTP_403"
    HTTP_404 = "HTTP_404"
    HTTP_429 = "HTTP_429"
    HTTP_ERROR = "HTTP_ERROR"          # 其它非 2xx（4xx/5xx 兜底）
    NOT_PDF = "NOT_PDF"
    NOT_EXPECTED_TYPE = "NOT_EXPECTED_TYPE"
    HTML_BLOCK_PAGE = "HTML_BLOCK_PAGE"
    EMPTY_BODY = "EMPTY_BODY"
    TOO_LARGE = "TOO_LARGE"
    CERTIFICATE_ERROR = "CERTIFICATE_ERROR"
    BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
    BROWSER_LAUNCH_FAILED = "BROWSER_LAUNCH_FAILED"
    BROWSER_NAVIGATION_FAILED = "BROWSER_NAVIGATION_FAILED"
    BROWSER_DOWNLOAD_FAILED = "BROWSER_DOWNLOAD_FAILED"
