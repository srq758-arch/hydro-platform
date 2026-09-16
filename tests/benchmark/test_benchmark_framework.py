"""测试 Benchmark 框架基础功能。

验证：
1. Ground Truth 数据加载
2. Benchmark Runner 初始化
3. 评估器计算
4. 报告生成
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 添加benchmark目录到路径以支持直接导入
benchmark_dir = Path(__file__).parent
sys.path.insert(0, str(benchmark_dir))

import benchmark_runner
import evaluator
import report_generator

BenchmarkRunner = benchmark_runner.BenchmarkRunner
CaseResult = benchmark_runner.CaseResult
BenchmarkEvaluator = evaluator.BenchmarkEvaluator
ReportGenerator = report_generator.ReportGenerator


def test_load_ground_truth():
    """测试1：加载 Ground Truth 数据"""
    print("\n=== 测试1：加载 Ground Truth 数据 ===")

    gt_path = Path(__file__).parent / "ground_truth" / "station_generation_cases.json"

    runner = BenchmarkRunner(gt_path)

    print(f"加载的样本数: {len(runner.cases)}")
    assert len(runner.cases) == 20, f"期望20个样本，实际{len(runner.cases)}个"

    # 验证第一个样本
    first_case = runner.cases[0]
    print(f"第一个样本: {first_case.case_id} - {first_case.canonical_name}")
    assert first_case.case_id == "gt_001"
    assert first_case.entity_id == "CHN_three_gorges_dam"
    assert first_case.expected_generation_gwh == 87800.0

    print("测试1通过")


def test_load_v5_2_development_and_holdout_manifests():
    """V5.2 manifest 字段演进不能让 benchmark 初始化失败。"""
    root = Path(__file__).parent / "ground_truth"
    development = BenchmarkRunner(root / "development_verified_v1.json")
    assert len(development.cases) == 4
    assert development.cases[0].expected_generation_gwh == 78790.0
    assert development.cases[0].source_content_kind == "pdf_table"
    assert development.cases[0].metric == "gross_generation"
    assert development.cases[0].measurement_scope == "plant"

    holdout = BenchmarkRunner(root / "holdout_inputs_v1.json")
    assert len(holdout.cases) == 5
    assert holdout.cases[0].expected_generation_gwh is None
    assert holdout.cases[0].source_url is None


def test_benchmark_unit_normalization_supports_energy_units():
    runner = BenchmarkRunner(Path(__file__).parent / "ground_truth" / "station_generation_cases.json")
    assert runner._normalize_unit("亿千瓦时") == "GWh"
    assert runner._normalize_unit("GWh") == "GWh"
    assert runner._normalize_unit("万度") == "MWh"


def test_evaluator():
    """测试2：评估器计算"""
    print("\n=== 测试2：评估器计算 ===")

    # 构造模拟结果
    mock_results = [
        CaseResult(
            case_id="test_001",
            case_name="Test Station 1",
            source_discovered=True,
            acquisition_success=True,
            parse_success=True,
            extraction_success=True,
            entity_match=True,
            year_match=True,
            unit_match=True,
            value_accuracy=1.0,
            overall_pass=True,
            error_stage=None,
            error_message=None,
            actual_generation_gwh=100.0,
            actual_year=2023,
            actual_unit="GWh"
        ),
        CaseResult(
            case_id="test_002",
            case_name="Test Station 2",
            source_discovered=True,
            acquisition_success=True,
            parse_success=False,
            extraction_success=False,
            entity_match=False,
            year_match=False,
            unit_match=False,
            value_accuracy=0.0,
            overall_pass=False,
            error_stage="parse",
            error_message="解析失败",
            actual_generation_gwh=None,
            actual_year=None,
            actual_unit=None
        )
    ]

    evaluator = BenchmarkEvaluator()
    report = evaluator.calculate_metrics(mock_results)

    print(f"总用例数: {report.total_cases}")
    print(f"整体准确率: {report.overall_record_accuracy:.1%}")
    print(f"来源发现率: {report.source_discovery_rate:.1%}")
    print(f"获取成功率: {report.acquisition_success_rate:.1%}")
    print(f"解析成功率: {report.parse_success_rate:.1%}")
    print(f"抽取成功率: {report.extraction_success_rate:.1%}")

    assert report.total_cases == 2
    assert report.overall_record_accuracy == 0.5  # 1/2
    assert report.source_discovery_rate == 1.0    # 2/2
    assert report.parse_success_rate == 0.5       # 1/2

    print("测试2通过")


def test_report_generation(tmp_path):
    """测试3：报告生成"""
    print("\n=== 测试3：报告生成 ===")

    # 构造模拟报告
    from evaluator import MetricsReport

    report = MetricsReport(
        total_cases=20,
        source_discovery_rate=0.95,
        acquisition_success_rate=0.90,
        parse_success_rate=0.85,
        extraction_success_rate=0.80,
        entity_match_accuracy=0.90,
        year_accuracy=0.95,
        unit_accuracy=0.85,
        value_accuracy_mean=0.88,
        value_accuracy_median=0.90,
        overall_record_accuracy=0.75,
        error_distribution={"parse": 2, "extraction": 3},
        failed_cases=[]
    )

    generator = ReportGenerator()
    output_path = tmp_path / "test_report.md"
    generator.generate_markdown(report, output_path)

    print(f"报告已生成: {output_path}")
    assert output_path.exists(), "报告文件未生成"

    # 验证报告内容
    content = output_path.read_text(encoding='utf-8')
    assert "Ground Truth Benchmark 评估报告" in content
    assert "整体准确率" in content
    assert "75.0%" in content

    print("测试3通过")


def test_value_accuracy_calculation():
    """测试4：值准确度计算"""
    print("\n=== 测试4：值准确度计算 ===")

    gt_path = Path(__file__).parent / "ground_truth" / "station_generation_cases.json"
    runner = BenchmarkRunner(gt_path)

    # 测试准确度计算
    # 误差 5% 内 -> 1.0
    acc1 = runner._calc_value_accuracy(100.0, 103.0)
    print(f"误差3%: {acc1:.2f}")
    assert acc1 == 1.0

    # 误差 10% 内 -> 0.9
    acc2 = runner._calc_value_accuracy(100.0, 108.0)
    print(f"误差8%: {acc2:.2f}")
    assert acc2 == 0.9

    # 误差 20% 内 -> 0.7
    acc3 = runner._calc_value_accuracy(100.0, 115.0)
    print(f"误差15%: {acc3:.2f}")
    assert acc3 == 0.7

    # 误差 20% 以上
    acc4 = runner._calc_value_accuracy(100.0, 150.0)
    print(f"误差50%: {acc4:.2f}")
    assert acc4 == 0.5

    print("测试4通过")


if __name__ == "__main__":
    print("=" * 60)
    print("Benchmark 框架功能测试")
    print("=" * 60)

    try:
        test_load_ground_truth()
        test_evaluator()
        test_report_generation()
        test_value_accuracy_calculation()

        print("\n" + "=" * 60)
        print("所有测试通过")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
