"""Ground Truth Benchmark工具

用于创建和管理人工标注的基准测试数据集，量化系统准确率。

功能：
1. 选择测试案例（电站+年份）
2. 人工标注正确答案
3. 对比系统输出与标准答案
4. 计算准确率指标
"""

import sys
from pathlib import Path
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
import sqlite3

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class GroundTruthManager:
    """Ground Truth基准数据管理器"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.benchmark_dir = project_root / "data" / "ground_truth"
        self.benchmark_dir.mkdir(parents=True, exist_ok=True)

    def create_test_cases(self, num_cases: int = 20) -> List[Dict[str, Any]]:
        """
        从数据库中选择测试案例

        选择标准：
        - 有官方网站的电站（更容易验证）
        - 不同国家、不同容量级别
        - 近3年数据
        """
        # 从stations表选择测试案例
        cursor = self.conn.execute("""
            SELECT
                entity_id,
                canonical_name,
                country,
                capacity_mw
            FROM stations
            WHERE capacity_mw IS NOT NULL
            AND capacity_mw > 100
            ORDER BY RANDOM()
            LIMIT ?
        """, (num_cases,))

        test_cases = []
        for row in cursor.fetchall():
            # 为每个电站选择最近3年
            for year in [2024, 2023, 2022]:
                test_cases.append({
                    "case_id": f"{row['entity_id']}_{year}",
                    "entity_id": row["entity_id"],
                    "station_name": row["canonical_name"],
                    "country": row["country"],
                    "capacity_mw": row["capacity_mw"],
                    "year": year,
                    "metric": "generation",
                    "ground_truth": None,  # 待人工标注
                    "annotated": False,
                    "annotation_date": None,
                    "annotator": None,
                    "source_url": None,
                    "notes": ""
                })

        return test_cases[:num_cases]

    def save_test_cases(self, test_cases: List[Dict[str, Any]], filename: str = None):
        """保存测试案例到JSON文件"""
        if filename is None:
            filename = f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        filepath = self.benchmark_dir / filename

        data = {
            "created_at": datetime.now().isoformat(),
            "total_cases": len(test_cases),
            "annotated_cases": sum(1 for c in test_cases if c["annotated"]),
            "test_cases": test_cases
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"测试案例已保存: {filepath}")
        return filepath

    def load_test_cases(self, filename: str) -> Dict[str, Any]:
        """加载测试案例"""
        filepath = self.benchmark_dir / filename

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return data

    def annotate_case(
        self,
        case_id: str,
        ground_truth: float,
        source_url: str,
        annotator: str,
        notes: str = ""
    ):
        """
        标注单个测试案例

        Args:
            case_id: 案例ID
            ground_truth: 标准答案（发电量，单位GWh）
            source_url: 数据来源URL
            annotator: 标注人员
            notes: 备注
        """
        return {
            "case_id": case_id,
            "ground_truth": ground_truth,
            "source_url": source_url,
            "annotated": True,
            "annotation_date": datetime.now().isoformat(),
            "annotator": annotator,
            "notes": notes
        }

    def get_system_output(self, entity_id: str, year: int) -> Optional[float]:
        """获取系统输出的结果"""
        cursor = self.conn.execute("""
            SELECT generation_gwh
            FROM generation_records
            WHERE entity_id = ?
            AND year = ?
            AND status = 'published'
            ORDER BY created_at DESC
            LIMIT 1
        """, (entity_id, year))

        row = cursor.fetchone()
        return row["generation_gwh"] if row else None

    def evaluate_benchmark(self, benchmark_file: str) -> Dict[str, Any]:
        """
        评估基准测试

        计算指标：
        - 准确率（完全匹配）
        - 平均误差
        - 覆盖率（系统有输出的案例比例）
        """
        data = self.load_test_cases(benchmark_file)
        test_cases = data["test_cases"]

        # 只评估已标注的案例
        annotated = [c for c in test_cases if c["annotated"]]

        if not annotated:
            return {
                "error": "没有已标注的案例",
                "total_cases": len(test_cases),
                "annotated_cases": 0
            }

        results = []
        exact_matches = 0
        total_error = 0
        covered = 0
        close_matches = 0  # 误差<5%

        for case in annotated:
            entity_id = case["entity_id"]
            year = case["year"]
            ground_truth = case["ground_truth"]

            # 获取系统输出
            system_output = self.get_system_output(entity_id, year)

            if system_output is not None:
                covered += 1

                # 计算误差
                error = abs(system_output - ground_truth)
                error_pct = error / ground_truth * 100 if ground_truth > 0 else 0

                # 判断匹配
                if error < 0.1:  # 0.1 GWh容差
                    exact_matches += 1
                if error_pct < 5:
                    close_matches += 1

                total_error += error_pct

                results.append({
                    "case_id": case["case_id"],
                    "station": case["station_name"],
                    "year": year,
                    "ground_truth": ground_truth,
                    "system_output": system_output,
                    "error_gwh": error,
                    "error_pct": error_pct,
                    "match": error < 0.1
                })
            else:
                results.append({
                    "case_id": case["case_id"],
                    "station": case["station_name"],
                    "year": year,
                    "ground_truth": ground_truth,
                    "system_output": None,
                    "error_gwh": None,
                    "error_pct": None,
                    "match": False
                })

        # 计算指标
        coverage_rate = covered / len(annotated) * 100
        exact_accuracy = exact_matches / covered * 100 if covered > 0 else 0
        close_accuracy = close_matches / covered * 100 if covered > 0 else 0
        avg_error = total_error / covered if covered > 0 else 0

        return {
            "benchmark_file": benchmark_file,
            "evaluation_date": datetime.now().isoformat(),
            "total_cases": len(annotated),
            "covered_cases": covered,
            "coverage_rate": coverage_rate,
            "exact_matches": exact_matches,
            "exact_accuracy": exact_accuracy,
            "close_matches": close_matches,
            "close_accuracy": close_accuracy,
            "avg_error_pct": avg_error,
            "results": results
        }

    def save_evaluation(self, evaluation: Dict[str, Any], filename: str = None):
        """保存评估结果"""
        if filename is None:
            filename = f"evaluation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        filepath = self.benchmark_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(evaluation, f, indent=2, ensure_ascii=False)

        print(f"评估结果已保存: {filepath}")
        return filepath

    def print_evaluation_report(self, evaluation: Dict[str, Any]):
        """打印评估报告"""
        print("\n" + "=" * 60)
        print("Ground Truth Benchmark 评估报告")
        print("=" * 60)

        print(f"\n基准文件: {evaluation['benchmark_file']}")
        print(f"评估时间: {evaluation['evaluation_date']}")

        print(f"\n测试案例数: {evaluation['total_cases']}")
        print(f"系统覆盖: {evaluation['covered_cases']}/{evaluation['total_cases']} ({evaluation['coverage_rate']:.1f}%)")

        if evaluation['covered_cases'] > 0:
            print(f"\n准确性指标:")
            print(f"  完全匹配: {evaluation['exact_matches']}/{evaluation['covered_cases']} ({evaluation['exact_accuracy']:.1f}%)")
            print(f"  接近匹配(<5%误差): {evaluation['close_matches']}/{evaluation['covered_cases']} ({evaluation['close_accuracy']:.1f}%)")
            print(f"  平均误差: {evaluation['avg_error_pct']:.2f}%")

        print(f"\n详细结果:")
        print(f"{'案例':<40} {'标准值':<12} {'系统值':<12} {'误差':<10} {'状态'}")
        print("-" * 80)

        for result in evaluation['results'][:10]:  # 只显示前10个
            case_id = result['case_id'][:38]
            gt = f"{result['ground_truth']:.1f}" if result['ground_truth'] else "N/A"
            sys_out = f"{result['system_output']:.1f}" if result['system_output'] is not None else "N/A"
            error = f"{result['error_pct']:.1f}%" if result['error_pct'] is not None else "N/A"
            status = "✓" if result['match'] else ("✗" if result['system_output'] is not None else "-")

            print(f"{case_id:<40} {gt:<12} {sys_out:<12} {error:<10} {status}")

        if len(evaluation['results']) > 10:
            print(f"\n... 还有 {len(evaluation['results']) - 10} 个案例未显示")

        print("\n" + "=" * 60)


def interactive_annotation_wizard():
    """交互式标注向导"""
    print("=" * 60)
    print("Ground Truth 标注向导")
    print("=" * 60)

    db_path = project_root / "data" / "hydropower.sqlite"
    manager = GroundTruthManager(db_path)

    # 1. 创建或加载测试案例
    print("\n[步骤1] 创建测试案例")
    print("1. 创建新的测试案例")
    print("2. 加载已有测试案例")

    choice = input("请选择 (1/2): ").strip()

    if choice == "1":
        num = input("创建多少个案例? (默认20): ").strip()
        num = int(num) if num else 20

        test_cases = manager.create_test_cases(num)
        filename = manager.save_test_cases(test_cases)

        print(f"\n已创建 {len(test_cases)} 个测试案例")
        print(f"文件: {filename}")

    elif choice == "2":
        print("\n可用的基准文件:")
        files = list(manager.benchmark_dir.glob("benchmark_*.json"))
        for i, f in enumerate(files, 1):
            print(f"{i}. {f.name}")

        if not files:
            print("没有找到基准文件，请先创建")
            return

        idx = int(input("选择文件 (输入编号): ").strip()) - 1
        filename = files[idx].name

        data = manager.load_test_cases(filename)
        test_cases = data["test_cases"]

        print(f"\n已加载 {len(test_cases)} 个案例")
        print(f"其中 {data['annotated_cases']} 个已标注")

    else:
        print("无效选择")
        return

    # 2. 标注案例
    print("\n[步骤2] 标注案例")
    print("为每个案例填写标准答案（人工查证）")

    annotator = input("标注人员姓名: ").strip()

    for i, case in enumerate(test_cases, 1):
        if case["annotated"]:
            continue

        print(f"\n--- 案例 {i}/{len(test_cases)} ---")
        print(f"电站: {case['station_name']}")
        print(f"国家: {case['country']}")
        print(f"装机: {case['capacity_mw']} MW")
        print(f"年份: {case['year']}")
        print(f"官网: {case['official_website']}")

        print("\n请访问官方网站或权威数据源，查证该年份的发电量")

        skip = input("标注此案例? (y/n/quit): ").strip().lower()

        if skip == 'quit':
            break
        elif skip == 'n':
            continue

        gt = input("发电量 (GWh): ").strip()
        source = input("数据来源URL: ").strip()
        notes = input("备注 (可选): ").strip()

        try:
            gt_value = float(gt)

            annotation = manager.annotate_case(
                case_id=case["case_id"],
                ground_truth=gt_value,
                source_url=source,
                annotator=annotator,
                notes=notes
            )

            # 更新case
            case.update(annotation)
            print(f"✓ 已标注")

        except ValueError:
            print("✗ 无效数值，跳过")

    # 3. 保存
    manager.save_test_cases(test_cases, filename)
    print(f"\n标注已保存: {filename}")


def evaluate_benchmark_cmd():
    """命令行评估基准测试"""
    print("=" * 60)
    print("Ground Truth 基准评估")
    print("=" * 60)

    db_path = project_root / "data" / "hydropower.sqlite"
    manager = GroundTruthManager(db_path)

    # 选择基准文件
    print("\n可用的基准文件:")
    files = list(manager.benchmark_dir.glob("benchmark_*.json"))

    if not files:
        print("没有找到基准文件，请先创建并标注")
        return

    for i, f in enumerate(files, 1):
        data = manager.load_test_cases(f.name)
        print(f"{i}. {f.name} ({data['annotated_cases']}/{data['total_cases']} 已标注)")

    idx = int(input("\n选择文件 (输入编号): ").strip()) - 1
    filename = files[idx].name

    # 评估
    print("\n开始评估...")
    evaluation = manager.evaluate_benchmark(filename)

    if "error" in evaluation:
        print(f"错误: {evaluation['error']}")
        return

    # 显示报告
    manager.print_evaluation_report(evaluation)

    # 保存结果
    save = input("\n保存评估结果? (y/n): ").strip().lower()
    if save == 'y':
        eval_file = manager.save_evaluation(evaluation)
        print(f"已保存: {eval_file}")


if __name__ == "__main__":
    print("Ground Truth Benchmark 工具")
    print("=" * 60)
    print("\n选择功能:")
    print("1. 创建并标注测试案例")
    print("2. 评估基准测试")

    choice = input("\n请选择 (1/2): ").strip()

    if choice == "1":
        interactive_annotation_wizard()
    elif choice == "2":
        evaluate_benchmark_cmd()
    else:
        print("无效选择")
