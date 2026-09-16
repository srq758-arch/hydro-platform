"""校验引擎（文档 13）。

对 ExtractionCandidate 做 Common+Master 校验，对 Project 记录做 Project 校验。
核心是识别文档 12.3 的混淆风险并落成 ValidationResult 里的问题码——
不修改数据、不猜测补齐，只判定并标注。低置信度/冲突/失败者应进 Review Queue。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..common.enums import (
    GenerationMetric,
    MeasurementScope,
    NormalizedEnergyUnit,
    PeriodType,
    ProjectStatus,
    Severity,
    ValueType,
)
from ..common.result import ValidationIssue, ValidationResult
from ..extraction.patterns import find_years
from ..models.candidate import ExtractionCandidate

# 单机满发年发电量上限（GWh）= capacity_mw * 8760h / 1000。乘以宽裕系数以容忍
# 抽水蓄能/合理误差；超出即判 CAPACITY_GENERATION_CONFLICT（几乎必是单位或范围错）。
_HOURS_PER_YEAR = 8760.0
_MAX_CAPACITY_FACTOR = 1.15
# 低置信度阈值：低于此值必须进复核（文档 15）。
_LOW_CONFIDENCE = 0.55


@dataclass
class ValidationContext:
    """校验上下文：提供交叉核对所需的已知事实（可空，缺失则跳过相关检查）。"""

    entity_capacity_mw: float | None = None
    expected_year: int | None = None
    expected_period_type: PeriodType | str = PeriodType.CALENDAR_YEAR
    # 已存在的 (period_label, value_type, scope) 集合，用于重复检测
    existing_keys: set[tuple] = field(default_factory=set)


def _max_annual_gwh(capacity_mw: float) -> float:
    return capacity_mw * _HOURS_PER_YEAR / 1000.0 * _MAX_CAPACITY_FACTOR


def _common_checks(cand: ExtractionCandidate, result: ValidationResult) -> None:
    """Common：必填/单位/数值范围（文档 13.1）。"""
    result.checked_fields.extend(["generation_gwh", "unit_raw", "normalized_unit", "period_label"])

    if cand.normalized_unit != NormalizedEnergyUnit.GWH:
        result.add_issue(
            "UNIT_UNCLEAR", "发电量未明确归一为 GWh", Severity.HIGH, "normalized_unit"
        )

    # 单位不清：抽取器已打 UNIT_UNCLEAR 或有原始值但无归一结果
    if "UNIT_UNCLEAR" in cand.flags:
        result.add_issue(
            "UNIT_UNCLEAR", "单位无法判定为能量单位", Severity.HIGH, "unit_raw"
        )
    if "UNIT_NOT_ENERGY" in cand.flags or "CAPACITY_SUSPECT" in cand.flags:
        # 原文单位是功率（MW 等），被误当发电量——典型 MW↔GWh 混淆
        result.add_issue(
            "CAPACITY_GENERATION_CONFLICT",
            "原文单位疑为功率(容量)而非发电量(能量)",
            Severity.HIGH,
            "unit_raw",
        )

    if cand.generation_gwh is not None and cand.generation_gwh < 0:
        result.add_issue(
            "VALUE_OUT_OF_RANGE", "发电量为负", Severity.HIGH, "generation_gwh"
        )


def _master_checks(
    cand: ExtractionCandidate, ctx: ValidationContext, result: ValidationResult
) -> None:
    """Master：身份/发电量/容量-发电量/年份/actual-forecast（文档 13.1）。"""
    result.checked_fields.extend(["metric", "value_type", "measurement_scope", "period_type"])

    if cand.metric in (None, GenerationMetric.UNKNOWN):
        result.add_issue(
            "METRIC_UNCLEAR", "未确认是总发电量、净发电量、上网电量或售电量", Severity.HIGH, "metric"
        )
    elif cand.metric != GenerationMetric.GROSS_GENERATION:
        result.add_issue(
            "METRIC_MISMATCH",
            f"指标 {cand.metric} 不是当前产品要求的总发电量",
            Severity.HIGH,
            "metric",
        )

    # actual/forecast 混淆：预测值不得冒充实际值
    if cand.value_type == ValueType.FORECAST:
        result.add_issue(
            "ACTUAL_FORECAST_MIXED",
            "候选为预测值(forecast)，不可当作实际发电量",
            Severity.HIGH,
            "value_type",
        )
    elif cand.value_type is None:
        result.add_issue(
            "ACTUAL_FORECAST_MIXED",
            "未判定 actual/forecast，无法确认是否为实际值",
            Severity.MEDIUM,
            "value_type",
        )

    # region/complex 冒充单站
    if cand.measurement_scope in (MeasurementScope.REGION, MeasurementScope.COMPLEX, MeasurementScope.GROUP):
        result.add_issue(
            "ENTITY_AMBIGUOUS",
            f"测量范围为 {cand.measurement_scope}，疑为区域/群合计而非单站",
            Severity.HIGH,
            "measurement_scope",
        )

    # 年份一致性：候选周期标签里的年份须与期望年份相符
    if ctx.expected_year is not None and cand.period_label:
        years = {int(y) for y in find_years(cand.period_label)}
        if years and ctx.expected_year not in years:
            result.add_issue(
                "YEAR_MISMATCH",
                f"周期标签年份 {sorted(years)} 与期望年份 {ctx.expected_year} 不符",
                Severity.HIGH,
                "period_label",
            )

    expected_period_type = (
        ctx.expected_period_type.value
        if isinstance(ctx.expected_period_type, PeriodType)
        else str(ctx.expected_period_type or PeriodType.CALENDAR_YEAR.value)
    )
    # 期间口径是任务契约的一部分：自然年任务不得把财年冒充全年，
    # 财年任务也不能接受模型抽出的自然年或未明确口径。
    if expected_period_type == PeriodType.CALENDAR_YEAR.value and cand.period_type == PeriodType.FISCAL_YEAR:
        result.add_issue(
            "YEAR_MISMATCH",
            "周期为财年(fiscal_year)，与日历年口径可能不一致",
            Severity.MEDIUM,
            "period_type",
        )
    elif expected_period_type == PeriodType.FISCAL_YEAR.value and cand.period_type != PeriodType.FISCAL_YEAR:
        result.add_issue(
            "PERIOD_AMBIGUOUS",
            "任务要求财政年度，但候选未识别为 fiscal_year",
            Severity.HIGH,
            "period_type",
        )
    if "PERIOD_UNCLEAR" in cand.flags:
        result.add_issue(
            "PERIOD_AMBIGUOUS",
            "仅识别到年份，未发现明确的全年/年度口径，不能确认是全年发电量",
            Severity.MEDIUM,
            "period_type",
        )

    # 容量-发电量冲突：年发电量超过装机满发理论上限
    if (
        cand.generation_gwh is not None
        and cand.generation_gwh > 0
        and ctx.entity_capacity_mw
    ):
        ceiling = _max_annual_gwh(ctx.entity_capacity_mw)
        if cand.generation_gwh > ceiling:
            result.add_issue(
                "CAPACITY_GENERATION_CONFLICT",
                f"年发电量 {cand.generation_gwh:.1f} GWh 超过装机 "
                f"{ctx.entity_capacity_mw} MW 的满发上限 {ceiling:.1f} GWh",
                Severity.HIGH,
                "generation_gwh",
            )

    # 重复记录
    key = (cand.period_label, cand.value_type, cand.measurement_scope)
    if key in ctx.existing_keys:
        result.add_issue(
            "DUPLICATE_RECORD", f"已存在同键记录 {key}", Severity.MEDIUM
        )


def validate_candidate(
    cand: ExtractionCandidate, ctx: ValidationContext | None = None
) -> ValidationResult:
    """对抽取候选做 Common+Master 校验。低置信度单独标注以驱动进复核。"""
    ctx = ctx or ValidationContext()
    result = ValidationResult()

    _common_checks(cand, result)
    _master_checks(cand, ctx, result)

    # 低置信度：文档 13.3 把「低置信度」与「校验失败」列为通向 Review 的两条独立路径，
    # 故它是复核触发项而非硬校验失败——记 issue 但不翻转 passed（否则会误拦升级）。
    if cand.confidence is not None and cand.confidence < _LOW_CONFIDENCE:
        result.issues.append(
            ValidationIssue(
                "LOW_CONFIDENCE",
                f"抽取置信度 {cand.confidence:.2f} 低于阈值 {_LOW_CONFIDENCE}",
                Severity.MEDIUM,
                "confidence",
            )
        )

    return result


def validate_project_record(
    *,
    status: str | None,
    capacity_mw: float | None,
    commissioning_year: int | None,
    current_year: int | None = None,
) -> ValidationResult:
    """Project 校验：状态/容量/投产时间自洽（文档 13.1）。"""
    result = ValidationResult(
        checked_fields=["status", "capacity_mw", "commissioning_year"]
    )

    if not status:
        result.add_issue(
            "MISSING_REQUIRED_FIELD", "项目状态缺失", Severity.MEDIUM, "status"
        )
    else:
        valid = {s.value for s in ProjectStatus}
        if status not in valid:
            result.add_issue(
                "PROJECT_STATUS_CONFLICT",
                f"项目状态 {status!r} 不在已知枚举 {sorted(valid)} 内",
                Severity.MEDIUM,
                "status",
            )

    if capacity_mw is not None and capacity_mw < 0:
        result.add_issue(
            "VALUE_OUT_OF_RANGE", "装机容量为负", Severity.HIGH, "capacity_mw"
        )

    # 已投产状态却无投产年份 → 冲突；投产年份晚于当前年 → 日期冲突
    if status == ProjectStatus.NEWLY_COMMISSIONED and commissioning_year is None:
        result.add_issue(
            "PROJECT_DATE_CONFLICT",
            "状态为已投产但缺投产年份",
            Severity.MEDIUM,
            "commissioning_year",
        )
    if (
        commissioning_year is not None
        and current_year is not None
        and commissioning_year > current_year
        and status == ProjectStatus.NEWLY_COMMISSIONED
    ):
        result.add_issue(
            "PROJECT_DATE_CONFLICT",
            f"已投产状态但投产年份 {commissioning_year} 晚于当前 {current_year}",
            Severity.HIGH,
            "commissioning_year",
        )

    return result
