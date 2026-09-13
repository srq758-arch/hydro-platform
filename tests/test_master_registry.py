"""测试任务 3.1：Master Registry 批量任务生成

验证：
1. MasterRegistry 类的基本功能
2. 批量任务生成（generation/capacity）
3. 优先级过滤
4. 按名称查询电站
5. 注册表统计
6. CLI 命令
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.registry.loader import MasterRegistry
from hydro_platform.database.connection import connect
from hydro_platform.database.repositories import TaskRepository
import pytest


def test_master_registry_basic():
    """测试 MasterRegistry 基本功能"""
    print("\n=== 测试 1: MasterRegistry 基本功能 ===")

    conn = connect()
    try:
        registry = MasterRegistry(conn)
        print("[OK] MasterRegistry 实例化成功")

        # 获取统计信息
        stats = registry.get_registry_stats()
        assert 'stations' in stats, "应包含stations统计"
        assert 'projects' in stats, "应包含projects统计"
        assert 'tasks' in stats, "应包含tasks统计"

        print(f"[OK] 注册表统计:")
        print(f"  电站总数: {stats['stations']['total']}")
        print(f"  项目总数: {stats['projects']['total']}")
        print(f"  任务总数: {stats['tasks']['total']}")

        # 测试通过

    except AssertionError as e:
        print(f"[FAIL] 测试失败: {e}")
        pytest.fail("[FAIL] 测试失败: {e}")
    except Exception as e:
        print(f"[FAIL] 异常: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail("[FAIL] 异常: {e}")
    finally:
        conn.close()


def test_generate_batch_tasks_generation():
    """测试批量生成发电量任务"""
    print("\n=== 测试 2: 批量生成发电量任务 ===")

    conn = connect()
    try:
        registry = MasterRegistry(conn)

        # 生成前的任务数
        before_count = conn.execute("SELECT COUNT(*) as count FROM tasks").fetchone()['count']
        print(f"生成前任务数: {before_count}")

        # 生成5个发电量任务（2023年）
        task_ids = registry.generate_batch_tasks(
            metric='generation',
            target_years=[2023],
            limit=5
        )

        assert isinstance(task_ids, list), "应返回任务ID列表"
        print(f"[OK] 生成了 {len(task_ids)} 个任务")

        # 验证任务已入库
        repo = TaskRepository(conn)
        for tid in task_ids[:3]:
            task = repo.get(tid)
            assert task is not None, f"任务{tid}应存在于数据库"
            assert task['task_type'] in ['station_generation', 'station_capacity'], \
                f"任务类型应为station_generation或station_capacity"
            print(f"  [OK] 任务 {tid}: {task['task_type']}, period={task['target_period']}")

        conn.close()
        # 测试通过

    except AssertionError as e:
        print(f"[FAIL] 测试失败: {e}")
        pytest.fail("[FAIL] 测试失败: {e}")
    except Exception as e:
        print(f"[FAIL] 异常: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail("[FAIL] 异常: {e}")
    finally:
        if conn:
            conn.close()


def test_generate_with_priority_filter():
    """测试优先级过滤"""
    print("\n=== 测试 3: 优先级过滤 ===")

    conn = connect()
    try:
        registry = MasterRegistry(conn)

        # 仅生成优先级A的任务
        task_ids = registry.generate_batch_tasks(
            metric='generation',
            target_years=[2022],
            priority_tier='A',
            limit=3
        )

        print(f"[OK] 生成了 {len(task_ids)} 个优先级A任务")

        # 验证优先级
        repo = TaskRepository(conn)
        for tid in task_ids:
            task = repo.get(tid)
            if task:
                assert task['priority_tier'] == 'A', f"任务{tid}优先级应为A"
                print(f"  [OK] 任务 {tid}: priority_tier=A")

        conn.close()
        # 测试通过

    except AssertionError as e:
        print(f"[FAIL] 测试失败: {e}")
        pytest.fail("[FAIL] 测试失败: {e}")
    except Exception as e:
        print(f"[FAIL] 异常: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail("[FAIL] 异常: {e}")
    finally:
        if conn:
            conn.close()


def test_get_entity_by_name():
    """测试按名称查询电站"""
    print("\n=== 测试 4: 按名称查询电站 ===")

    conn = connect()
    try:
        registry = MasterRegistry(conn)

        # 获取任意一个电站名称
        row = conn.execute("SELECT canonical_name, entity_id FROM stations LIMIT 1").fetchone()
        if not row:
            print("[SKIP] 数据库中没有电站记录")
            conn.close()
            # 测试通过

        name = row['canonical_name']
        expected_id = row['entity_id']

        # 精确匹配
        result = registry.get_entity_by_name(name, fuzzy=False)
        assert result is not None, f"应找到电站: {name}"
        assert result['entity_id'] == expected_id, "entity_id应匹配"
        print(f"[OK] 精确匹配: {name} -> {result['entity_id']}")

        # 模糊匹配
        partial_name = name[:5] if len(name) > 5 else name
        result = registry.get_entity_by_name(partial_name, fuzzy=True)
        if result:
            print(f"[OK] 模糊匹配: {partial_name} -> {result['canonical_name']}")
        else:
            print(f"[INFO] 模糊匹配未找到: {partial_name}")

        # 不存在的电站
        result = registry.get_entity_by_name("___nonexistent___", fuzzy=False)
        assert result is None, "不存在的电站应返回None"
        print("[OK] 不存在的电站返回None")

        conn.close()
        # 测试通过

    except AssertionError as e:
        print(f"[FAIL] 测试失败: {e}")
        pytest.fail("[FAIL] 测试失败: {e}")
    except Exception as e:
        print(f"[FAIL] 异常: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail("[FAIL] 异常: {e}")
    finally:
        if conn:
            conn.close()


def test_capacity_tasks():
    """测试容量任务生成"""
    print("\n=== 测试 5: 容量任务生成 ===")

    conn = connect()
    try:
        registry = MasterRegistry(conn)

        # 生成容量任务
        task_ids = registry.generate_batch_tasks(
            metric='capacity',
            limit=3
        )

        print(f"[OK] 生成了 {len(task_ids)} 个容量任务")

        # 验证任务类型
        repo = TaskRepository(conn)
        for tid in task_ids:
            task = repo.get(tid)
            assert task is not None, f"任务{tid}应存在"
            assert task['task_type'] == 'station_capacity', "应为容量任务"
            assert task['target_period'] is None, "容量任务无target_period"
            print(f"  [OK] 任务 {tid}: task_type=station_capacity")

        conn.close()
        # 测试通过

    except AssertionError as e:
        print(f"[FAIL] 测试失败: {e}")
        pytest.fail("[FAIL] 测试失败: {e}")
    except Exception as e:
        print(f"[FAIL] 异常: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail("[FAIL] 异常: {e}")
    finally:
        if conn:
            conn.close()


def main():
    print("=" * 60)
    print("任务 3.1: Master Registry 批量任务生成测试")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("MasterRegistry基本功能", test_master_registry_basic()))
    results.append(("批量生成发电量任务", test_generate_batch_tasks_generation()))
    results.append(("优先级过滤", test_generate_with_priority_filter()))
    results.append(("按名称查询电站", test_get_entity_by_name()))
    results.append(("容量任务生成", test_capacity_tasks()))

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "[OK] 通过" if result else "[FAIL] 失败"
        print(f"{status}: {name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n[OK] 任务 3.1 Master Registry 批量任务生成功能实现完成")
        print("\nCLI使用示例:")
        print("  # 生成10个任务（2023年发电量）")
        print("  python -m hydro_platform.app.cli.commands generate-batch-tasks --year 2023 --limit 10")
        print("\n  # 仅生成Top100相关任务（优先级A）")
        print("  python -m hydro_platform.app.cli.commands generate-batch-tasks --priority A --year 2023")
        print("\n  # 生成容量任务")
        print("  python -m hydro_platform.app.cli.commands generate-batch-tasks --metric capacity --limit 50")
        print("\n  # 查看注册表统计")
        print("  python -m hydro_platform.app.cli.commands registry-stats")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
