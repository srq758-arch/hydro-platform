"""Benchmark 评估器。

计算各项评估指标，生成评估报告。
"""

from __future__ import annotations

from typing import List
from dataclasses import dataclass
import numpy as np

try:
    from .benchmark_runner import CaseResult
except ImportError:
    from benchmark_runner import CaseResult


@dataclass
class MetricsReport:
    """评估指标报告"""
    total_cases: int

    # 阶段成功率
    source_discovery_rate: float
    acquisition_success_rate: float
    parse_success_rate: float
    extraction_success_rate: float

    # 字段准确率
    entity_match_accuracy: float
    year_accuracy: float
    unit_accuracy: float

    # 值准确度
    value_accuracy_mean: float
    value_accuracy_median: float

    # 整体准确率
    overall_record_accuracy: float

    # 错误分布
    error_distribution: dict

    # 失败案例
    failed_cases: List[CaseResult]


class BenchmarkEvaluator:
    """Benchmark 评估器"""

    def calculate_metrics(self, results: List[CaseResult]) -> MetricsReport:
        """计算评估指标"""
        total = len(results)

        if total == 0:
            return self._empty_report()

        # 阶段成功率
        source_discovery_rate = sum(r.source_discovered for r in results) / total
        acquisition_success_rate = sum(r.acquisition_success for r in results) / total
        parse_success_rate = sum(r.parse_success for r in results) / total
        extraction_success_rate = sum(r.extraction_success for r in results) / total

        # 字段准确率
        entity_match_accuracy = sum(r.entity_match for r in results) / total
        year_accuracy = sum(r.year_match for r in results) / total
        unit_accuracy = sum(r.unit_match for r in results) / total

        # 值准确度
        value_accuracies = [r.value_accuracy for r in results]
        value_accuracy_mean = np.mean(value_accuracies)
        value_accuracy_median = np.median(value_accuracies)

        # 整体准确率
        overall_record_accuracy = sum(r.overall_pass for r in results) / total

        # 错误分布
        error_distribution = self._count_errors_by_stage(results)

        # 失败案例
        failed_cases = [r for r in results if not r.overall_pass]

        return MetricsReport(
            total_cases=total,
            source_discovery_rate=source_discovery_rate,
            acquisition_success_rate=acquisition_success_rate,
            parse_success_rate=parse_success_rate,
            extraction_success_rate=extraction_success_rate,
            entity_match_accuracy=entity_match_accuracy,
            year_accuracy=year_accuracy,
            unit_accuracy=unit_accuracy,
            value_accuracy_mean=value_accuracy_mean,
            value_accuracy_median=value_accuracy_median,
            overall_record_accuracy=overall_record_accuracy,
            error_distribution=error_distribution,
            failed_cases=failed_cases
        )

    def _empty_report(self) -> MetricsReport:
        """空报告"""
        return MetricsReport(
            total_cases=0,
            source_discovery_rate=0.0,
            acquisition_success_rate=0.0,
            parse_success_rate=0.0,
            extraction_success_rate=0.0,
            entity_match_accuracy=0.0,
            year_accuracy=0.0,
            unit_accuracy=0.0,
            value_accuracy_mean=0.0,
            value_accuracy_median=0.0,
            overall_record_accuracy=0.0,
            error_distribution={},
            failed_cases=[]
        )

    def _count_errors_by_stage(self, results: List[CaseResult]) -> dict:
        """统计各阶段错误数量"""
        error_counts = {}

        for result in results:
            if result.error_stage:
                stage = result.error_stage
                error_counts[stage] = error_counts.get(stage, 0) + 1

        return error_counts
