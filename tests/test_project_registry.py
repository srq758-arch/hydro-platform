"""测试任务 3.2：Project Registry 实现

验证：
1. ProjectRegistry 基本功能
2. 项目注册
3. 状态更新与历史跟踪
4. 按状态查询项目
5. 批量生成项目任务
6. 统计信息
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.registry.project_registry import ProjectRegistry
from hydro_platform.database.connection import connect
from hydro_platform.database.repositories import TaskRepository
from hydro_platform.models.project import Project
from hydro_platform.common.clock import now_iso
import pytest


def test_project_registry_basic():
    """测试 ProjectRegistry 基本功能"""
    print("\n=== 测试 1: ProjectRegistry 基本功能 ===")

    conn = connect()
    try:
        registry = ProjectRegistry(conn)
        print("[OK] ProjectRegistry 实例化成功")

        # 获取统计信息
        stats = registry.get_registry_stats()
        assert 'projects' in stats, "应包含projects统计"

        print(f"[OK] 项目注册表统计:")
        print(f"  项目总数: {stats['projects']['total']}")
        print(f"  在建: {stats['projects']['under_construction']}")
        print(f"  新投产: {stats['projects']['newly_commissioned']}")

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


def test_register_project():
    """测试注册项目"""
    print("\n=== 测试 2: 注册项目 ===")

    conn = connect()
    try:
        registry = ProjectRegistry(conn)

        # 创建测试项目
        project = Project(
            entity_id='test_project_001',
            canonical_name='Test Hydropower Project',
            country='CN',
            capacity_mw=2000.0,
            status='announced',
            commissioning_year=2026,
            priority_tier='B',
            collection_priority=100
        )

        # 注册项目
        entity_id = registry.register_project(project)
        assert entity_id == 'test_project_001', "应返回正确的entity_id"
        print(f"[OK] 注册项目: {entity_id}")

        # 验证项目已入库
        stored = registry.get_project(entity_id)
        assert stored is not None, "项目应存在于数据库"
        assert stored['canonical_name'] == 'Test Hydropower Project', "名称应匹配"
        assert stored['capacity_mw'] == 2000.0, "容量应匹配"
        print(f"[OK] 项目已入库: {stored['canonical_name']}, {stored['capacity_mw']} MW")

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


def test_update_status():
    """测试状态更新与历史跟踪"""
    print("\n=== 测试 3: 状态更新与历史跟踪 ===")

    conn = connect()
    try:
        registry = ProjectRegistry(conn)

        project_id = 'test_project_001'

        # 更新状态 1: announced -> approved
        registry.update_project_status(
            project_id=project_id,
            new_status='approved',
            effective_date='2024-01-15',
            notes='政府批准文件'
        )
        print("[OK] 状态更新 1: announced -> approved")

        # 更新状态 2: approved -> under_construction
        registry.update_project_status(
            project_id=project_id,
            new_status='under_construction',
            effective_date='2024-06-01',
            notes='开工建设'
        )
        print("[OK] 状态更新 2: approved -> under_construction")

        # 验证当前状态
        project = registry.get_project(project_id)
        assert project['status'] == 'under_construction', "当前状态应为under_construction"
        print(f"[OK] 当前状态: {project['status']}")

        # 获取历史记录
        history = registry.get_status_history(project_id)
        assert len(history) >= 2, "应有至少2条历史记录"
        print(f"[OK] 历史记录数: {len(history)}")

        # 验证历史记录顺序（最新的在前）
        assert history[0]['status'] == 'under_construction', "最新记录应为under_construction"
        assert history[1]['status'] == 'approved', "第二条记录应为approved"
        print("[OK] 历史记录顺序正确")

        for h in history[:2]:
            print(f"  - {h['status']} (生效日期: {h['effective_date']}, 备注: {h.get('notes', 'N/A')})")

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


def test_query_by_status():
    """测试按状态查询项目"""
    print("\n=== 测试 4: 按状态查询项目 ===")

    conn = connect()
    try:
        registry = ProjectRegistry(conn)

        # 查询在建项目
        projects = registry.query_projects_by_status(status='under_construction', limit=5)
        print(f"[OK] 查询到 {len(projects)} 个在建项目")

        if projects:
            for p in projects[:3]:
                print(f"  - {p['canonical_name']} ({p['country']}, {p.get('capacity_mw', 'N/A')} MW)")

        # 查询特定国家的项目
        cn_projects = registry.query_projects_by_status(country='CN', limit=3)
        print(f"[OK] 查询到 {len(cn_projects)} 个中国项目")

        # 查询年份范围
        recent = registry.query_projects_by_status(year_range=(2024, 2026), limit=5)
        print(f"[OK] 查询到 {len(recent)} 个2024-2026年投产项目")

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


def test_generate_project_tasks():
    """测试批量生成项目任务"""
    print("\n=== 测试 5: 批量生成项目任务 ===")

    conn = connect()
    try:
        registry = ProjectRegistry(conn)

        # 生成在建项目的任务
        task_ids = registry.generate_project_tasks(
            status_filter='under_construction',
            limit=3
        )

        print(f"[OK] 生成了 {len(task_ids)} 个项目任务")

        # 验证任务已入库
        repo = TaskRepository(conn)
        for tid in task_ids[:3]:
            task = repo.get(tid)
            assert task is not None, f"任务{tid}应存在"
            assert task['task_type'] in ['project_status', 'project_commissioning'], \
                "任务类型应为project相关"
            print(f"  [OK] 任务 {tid}: {task['task_type']}")

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


def test_list_projects():
    """测试项目列表"""
    print("\n=== 测试 6: 项目列表 ===")

    conn = connect()
    try:
        registry = ProjectRegistry(conn)

        # 按容量排序
        projects = registry.list_projects(limit=5, order_by='capacity_mw')
        print(f"[OK] 获取到 {len(projects)} 个项目（按容量排序）")

        if projects:
            for p in projects[:3]:
                capacity = p.get('capacity_mw', 0) or 0
                print(f"  - {p['canonical_name']}: {capacity:.1f} MW")

        # 按年份排序
        projects_by_year = registry.list_projects(limit=5, order_by='commissioning_year')
        print(f"[OK] 获取到 {len(projects_by_year)} 个项目（按年份排序）")

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
    print("任务 3.2: Project Registry 实现测试")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("ProjectRegistry基本功能", test_project_registry_basic()))
    results.append(("注册项目", test_register_project()))
    results.append(("状态更新与历史跟踪", test_update_status()))
    results.append(("按状态查询项目", test_query_by_status()))
    results.append(("批量生成项目任务", test_generate_project_tasks()))
    results.append(("项目列表", test_list_projects()))

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
        print("\n[OK] 任务 3.2 Project Registry 实现完成")
        print("\nCLI使用示例:")
        print("  # 生成在建项目任务")
        print("  python -m hydro_platform.app.cli.commands generate-project-tasks --status under_construction --limit 10")
        print("\n  # 查看项目统计")
        print("  python -m hydro_platform.app.cli.commands project-stats")
        print("\n  # 更新项目状态")
        print("  python -m hydro_platform.app.cli.commands update-project-status --project-id=PRJ001 --status=under_construction --date=2024-06-01")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
