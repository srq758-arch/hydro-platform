"""Benchmark 报告生成器。

生成 Markdown 格式的评估报告。
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

try:
    from .evaluator import MetricsReport
except ImportError:
    from evaluator import MetricsReport


class ReportGenerator:
    """报告生成器"""

    def generate_markdown(self, report: MetricsReport, output_path: Path):
        """生成 Markdown 报告"""

        content = self._build_markdown_content(report)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

    def _build_markdown_content(self, report: MetricsReport) -> str:
        """构建 Markdown 内容"""

        lines = []

        # 标题
        lines.append("# Ground Truth Benchmark 评估报告")
        lines.append("")
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"测试用例数: {report.total_cases}")
        lines.append("")

        # 整体准确率
        lines.append("## 整体准确率")
        lines.append("")
        lines.append(f"**{report.overall_record_accuracy:.1%}**")
        lines.append("")

        if report.overall_record_accuracy >= 0.8:
            lines.append("✓ 达标（目标 ≥ 80%）")
        else:
            lines.append("✗ 未达标（目标 ≥ 80%）")
        lines.append("")

        # 阶段成功率
        lines.append("## 阶段成功率")
        lines.append("")
        lines.append("| 阶段 | 成功率 |")
        lines.append("|------|--------|")
        lines.append(f"| 来源发现 (Source Discovery) | {report.source_discovery_rate:.1%} |")
        lines.append(f"| 资料获取 (Acquisition) | {report.acquisition_success_rate:.1%} |")
        lines.append(f"| 内容解析 (Parsing) | {report.parse_success_rate:.1%} |")
        lines.append(f"| 数据抽取 (Extraction) | {report.extraction_success_rate:.1%} |")
        lines.append("")

        # 字段准确率
        lines.append("## 字段准确率")
        lines.append("")
        lines.append("| 字段 | 准确率 |")
        lines.append("|------|--------|")
        lines.append(f"| 电站匹配 (Entity Match) | {report.entity_match_accuracy:.1%} |")
        lines.append(f"| 年份识别 (Year) | {report.year_accuracy:.1%} |")
        lines.append(f"| 单位识别 (Unit) | {report.unit_accuracy:.1%} |")
        lines.append("")

        # 值准确度
        lines.append("## 发电量值准确度")
        lines.append("")
        lines.append(f"- 平均准确度: {report.value_accuracy_mean:.1%}")
        lines.append(f"- 中位数准确度: {report.value_accuracy_median:.1%}")
        lines.append("")

        # 错误分布
        if report.error_distribution:
            lines.append("## 错误分布")
            lines.append("")
            lines.append("| 失败阶段 | 数量 |")
            lines.append("|----------|------|")
            for stage, count in sorted(report.error_distribution.items(), key=lambda x: -x[1]):
                lines.append(f"| {stage} | {count} |")
            lines.append("")

        # 失败案例详情
        if report.failed_cases:
            lines.append("## 失败案例详情")
            lines.append("")

            for case in report.failed_cases:
                lines.append(f"### {case.case_id}: {case.case_name}")
                lines.append("")
                lines.append(f"- 失败阶段: {case.error_stage or 'N/A'}")
                lines.append(f"- 错误信息: {case.error_message or 'N/A'}")
                lines.append("")

                lines.append("**字段对比:**")
                lines.append("")
                lines.append("| 字段 | 期望值 | 实际值 | 匹配 |")
                lines.append("|------|--------|--------|------|")
                lines.append(f"| 年份 | - | {case.actual_year or 'N/A'} | {'✓' if case.year_match else '✗'} |")
                lines.append(f"| 单位 | - | {case.actual_unit or 'N/A'} | {'✓' if case.unit_match else '✗'} |")
                lines.append(f"| 发电量 | - | {case.actual_generation_gwh or 'N/A'} GWh | {case.value_accuracy:.1%} |")
                lines.append("")

        # 改进建议
        lines.append("## 改进建议")
        lines.append("")

        if report.source_discovery_rate < 0.9:
            lines.append("- **来源发现率较低**：检查 Discovery 模块的官方来源和权威来源配置")

        if report.acquisition_success_rate < 0.9:
            lines.append("- **资料获取失败较多**：检查 HTTP Client 和 Playwright Client 的错误处理")

        if report.parse_success_rate < 0.9:
            lines.append("- **解析失败较多**：检查 Parser 对各种文件格式的支持")

        if report.extraction_success_rate < 0.8:
            lines.append("- **抽取成功率低**：优化规则抽取逻辑和 LLM Prompt")

        if report.year_accuracy < 0.95:
            lines.append("- **年份识别不准确**：优化年份抽取正则表达式和 LLM 指令")

        if report.unit_accuracy < 0.95:
            lines.append("- **单位识别不准确**：检查单位标准化逻辑，防止 MW/GWh 混淆")

        if report.value_accuracy_mean < 0.90:
            lines.append("- **发电量值偏差较大**：检查数值抽取逻辑，防止小数点、千分位等格式问题")

        if not lines[-1].startswith("-"):
            lines.append("- 当前各项指标均达标，继续保持")

        lines.append("")

        return "\n".join(lines)
