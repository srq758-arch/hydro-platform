"""运行完整的 Ground Truth Benchmark。

执行所有20个Ground Truth案例，生成完整评估报告。
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 添加benchmark目录到路径
benchmark_dir = Path(__file__).parent
sys.path.insert(0, str(benchmark_dir))

import benchmark_runner
import evaluator
import report_generator

from hydro_platform.common.logging_setup import get_logger

logger = get_logger(__name__)


def main():
    """运行完整benchmark"""

    print("=" * 70)
    print("Ground Truth Benchmark - 完整运行")
    print("=" * 70)
    print()

    # 1. 加载Ground Truth数据
    gt_path = Path(__file__).parent / "ground_truth" / "station_generation_cases.json"
    print(f"加载Ground Truth数据: {gt_path}")

    runner = benchmark_runner.BenchmarkRunner(gt_path)
    print(f"[OK] 加载了 {len(runner.cases)} 个测试用例")
    print()

    # 2. 运行benchmark
    print("开始运行Pipeline...")
    print("-" * 70)

    results = runner.run_all()

    print()
    print("-" * 70)
    print(f"[OK] 完成，共 {len(results)} 个结果")
    print()

    # 3. 评估结果
    print("评估结果...")
    eval = evaluator.BenchmarkEvaluator()
    report = eval.calculate_metrics(results)

    print(f"[OK] 整体准确率: {report.overall_record_accuracy:.1%}")
    print()

    # 4. 生成报告
    output_dir = Path(__file__).parent / "reports"
    output_dir.mkdir(exist_ok=True)

    report_path = output_dir / "benchmark_report.md"
    print(f"生成报告: {report_path}")

    gen = report_generator.ReportGenerator()
    gen.generate_markdown(report, report_path)

    print(f"[OK] 报告已生成")
    print()

    # 5. 打印关键指标
    print("=" * 70)
    print("关键指标总结")
    print("=" * 70)
    print()
    print(f"测试用例总数:        {report.total_cases}")
    print(f"整体准确率:          {report.overall_record_accuracy:.1%}")
    print()
    print("阶段成功率:")
    print(f"  源发现率:          {report.source_discovery_rate:.1%}")
    print(f"  获取成功率:        {report.acquisition_success_rate:.1%}")
    print(f"  解析成功率:        {report.parse_success_rate:.1%}")
    print(f"  抽取成功率:        {report.extraction_success_rate:.1%}")
    print()
    print("字段准确率:")
    print(f"  实体匹配:          {report.entity_match_accuracy:.1%}")
    print(f"  年份准确:          {report.year_accuracy:.1%}")
    print(f"  单位准确:          {report.unit_accuracy:.1%}")
    print()
    print("值准确度:")
    print(f"  平均准确度:        {report.value_accuracy_mean:.1%}")
    print(f"  中位数准确度:      {report.value_accuracy_median:.1%}")
    print()

    # 6. 验收标准检查
    print("=" * 70)
    print("验收标准检查")
    print("=" * 70)
    print()

    passed = True

    # 标准1: 整体准确率 >= 95%
    if report.overall_record_accuracy >= 0.95:
        print("[OK] 整体准确率 >= 95% - 通过")
    else:
        print(f"[X] 整体准确率 {report.overall_record_accuracy:.1%} < 95% - 未达标")
        passed = False

    # 标准2: 覆盖Top 20电站
    if report.total_cases >= 20:
        print("[OK] 覆盖Top 20电站 - 通过")
    else:
        print(f"[X] 仅覆盖 {report.total_cases} 个电站 < 20 - 未达标")
        passed = False

    # 标准3: 可自动化运行
    print("[OK] 自动化回归测试 - 通过")

    print()

    if passed:
        print("=" * 70)
        print("[OK] P0-2 验收标准：全部通过")
        print("=" * 70)
        return 0
    else:
        print("=" * 70)
        print("[X] P0-2 验收标准：未完全通过")
        print("=" * 70)
        print()
        print("建议:")
        if report.overall_record_accuracy < 0.95:
            print("- 检查失败案例，优化Pipeline各阶段")
            print(f"- 当前有 {len(report.failed_cases)} 个失败案例")
            print("- 查看详细报告: reports/benchmark_report.md")
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f"\n运行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
