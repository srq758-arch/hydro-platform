"""测试Ground Truth Benchmark工具

验证项：
1. 工具能否正常导入
2. 创建测试案例
3. 标注功能
4. 评估功能
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tools"))

from ground_truth_benchmark import GroundTruthManager


def test_import():
    """测试1：导入成功"""
    print("\n=== 测试1：工具导入 ===")
    print("[PASS] GroundTruthManager导入成功")
    return True


def test_manager_init():
    """测试2：初始化Manager"""
    print("\n=== 测试2：初始化Manager ===")

    db_path = project_root / "data" / "hydropower.sqlite"

    if not db_path.exists():
        print(f"[SKIP] 数据库不存在: {db_path}")
        return None

    try:
        manager = GroundTruthManager(db_path)
        print(f"数据库路径: {manager.db_path}")
        print(f"基准目录: {manager.benchmark_dir}")
        print(f"基准目录存在: {manager.benchmark_dir.exists()}")

        manager.conn.close()

        print("[PASS] Manager初始化成功")
        return True
    except Exception as e:
        print(f"[FAIL] 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_create_test_cases():
    """测试3：创建测试案例"""
    print("\n=== 测试3：创建测试案例 ===")

    db_path = project_root / "data" / "hydropower.sqlite"

    if not db_path.exists():
        print("[SKIP] 数据库不存在")
        return None

    try:
        manager = GroundTruthManager(db_path)

        # 创建5个测试案例
        test_cases = manager.create_test_cases(num_cases=5)

        print(f"创建了 {len(test_cases)} 个测试案例")

        if test_cases:
            print(f"\n示例案例:")
            case = test_cases[0]
            print(f"  case_id: {case['case_id']}")
            print(f"  station: {case['station_name']}")
            print(f"  country: {case['country']}")
            print(f"  year: {case['year']}")
            print(f"  capacity_mw: {case['capacity_mw']}")
            print(f"  ground_truth: {case['ground_truth']} (待标注)")

        manager.conn.close()

        print("[PASS] 测试案例创建成功")
        return True

    except Exception as e:
        print(f"[FAIL] 创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_save_and_load():
    """测试4：保存和加载"""
    print("\n=== 测试4：保存和加载测试案例 ===")

    db_path = project_root / "data" / "hydropower.sqlite"

    if not db_path.exists():
        print("[SKIP] 数据库不存在")
        return None

    try:
        manager = GroundTruthManager(db_path)

        # 创建并保存
        test_cases = manager.create_test_cases(num_cases=3)
        filename = manager.save_test_cases(test_cases, filename="test_benchmark.json")

        print(f"保存到: {filename}")

        # 加载
        loaded_data = manager.load_test_cases("test_benchmark.json")

        print(f"加载的案例数: {loaded_data['total_cases']}")
        print(f"已标注案例数: {loaded_data['annotated_cases']}")

        assert len(loaded_data['test_cases']) == len(test_cases), "案例数量不匹配"

        manager.conn.close()

        print("[PASS] 保存和加载成功")
        return True

    except Exception as e:
        print(f"[FAIL] 保存/加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_annotation():
    """测试5：标注功能"""
    print("\n=== 测试5：标注功能 ===")

    db_path = project_root / "data" / "hydropower.sqlite"

    if not db_path.exists():
        print("[SKIP] 数据库不存在")
        return None

    try:
        manager = GroundTruthManager(db_path)

        # 创建测试案例
        test_cases = manager.create_test_cases(num_cases=2)
        case_id = test_cases[0]['case_id']

        # 标注一个案例
        updated_case = manager.annotate_case(
            case_id=case_id,
            ground_truth=82911.0,  # 三峡2024年发电量
            source_url="https://www.ctg.com.cn/ndbg/2024/",
            annotator="测试员",
            notes="测试标注"
        )

        print(f"标注案例: {case_id}")
        print(f"  ground_truth: {updated_case['ground_truth']}")
        print(f"  source_url: {updated_case['source_url']}")
        print(f"  annotator: {updated_case['annotator']}")
        print(f"  annotated: {updated_case['annotated']}")

        assert updated_case['annotated'] == True, "标注状态应为True"
        assert updated_case['ground_truth'] == 82911.0, "ground_truth值不正确"

        manager.conn.close()

        print("[PASS] 标注功能正常")
        return True

    except Exception as e:
        print(f"[FAIL] 标注失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("=" * 60)
    print("Ground Truth Benchmark 工具测试")
    print("=" * 60)

    results = []

    # 测试1：导入
    import_ok = test_import()
    results.append(("工具导入", import_ok))

    # 测试2：初始化
    init_ok = test_manager_init()
    results.append(("Manager初始化", init_ok))

    # 测试3：创建案例
    create_ok = test_create_test_cases()
    results.append(("创建测试案例", create_ok))

    # 测试4：保存和加载
    save_load_ok = test_save_and_load()
    results.append(("保存和加载", save_load_ok))

    # 测试5：标注
    annotate_ok = test_annotation()
    results.append(("标注功能", annotate_ok))

    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总:")
    print("=" * 60)

    for name, result in results:
        if result is True:
            status = "[PASS]"
        elif result is False:
            status = "[FAIL]"
        else:
            status = "[SKIP]"
        print(f"{status} {name}")

    failed = [name for name, result in results if result is False]

    if failed:
        print(f"\n{len(failed)} 个测试失败")
        return 1
    else:
        print("\n所有测试通过")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
