"""测试任务 3.3：Project-Station Linking 机制

验证：
1. 手动建立关联（commissioning/expansion/upgrade）
2. 查询电站的项目历史
3. 查询项目对应的电站
4. 删除关联
5. 自动关联（按名称+年份）
6. 关联统计
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.registry.project_station_linker import ProjectStationLinker
from hydro_platform.registry.project_registry import ProjectRegistry
from hydro_platform.database.connection import connect
from hydro_platform.models.project import Project
from hydro_platform.models.station import Station
from hydro_platform.database.repositories import StationRepository
import pytest


def setup_test_data(conn):
    """创建测试数据"""
    # 创建测试项目
    project = Project(
        entity_id='test_proj_link_001',
        canonical_name='Test Dam Project',
        country='CN',
        capacity_mw=5000.0,
        status='newly_commissioned',
        commissioning_year=2023,
        priority_tier='B',
        collection_priority=100
    )

    registry = ProjectRegistry(conn)
    registry.register_project(project)

    # 创建测试电站
    conn.execute("""
        INSERT OR REPLACE INTO stations (
            entity_id, entity_type, canonical_name, country,
            capacity_mw, commissioning_year, priority_tier, collection_priority
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        'test_sta_link_001', 'station', 'Test Dam Station', 'CN',
        5000.0, 2023, 'B', 100
    ))

    conn.commit()
    return 'test_proj_link_001', 'test_sta_link_001'


def test_commissioning_link():
    """测试投产关联"""
    print("\n=== 测试 1: 投产关联 ===")

    conn = connect()
    try:
        project_id, station_id = setup_test_data(conn)
        linker = ProjectStationLinker(conn)

        # 建立投产关联
        link_id = linker.link_on_commissioning(
            project_id=project_id,
            station_id=station_id,
            commissioning_date='2023-06-15',
            confidence=1.0,
            notes='测试投产关联'
        )

        assert link_id > 0, "应返回有效的link_id"
        print(f"[OK] 建立投产关联: link_id={link_id}")

        # 验证关联已创建
        link = linker.get_link(project_id, station_id, 'commissioning')
        assert link is not None, "关联应存在"
        assert link['link_type'] == 'commissioning', "类型应为commissioning"
        assert link['effective_date'] == '2023-06-15', "日期应匹配"
        print(f"[OK] 关联记录: {link['link_type']}, {link['effective_date']}")

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


def test_expansion_and_upgrade_links():
    """测试扩建和改造关联"""
    print("\n=== 测试 2: 扩建和改造关联 ===")

    conn = connect()
    try:
        linker = ProjectStationLinker(conn)

        # 创建扩建项目
        project_id_exp = 'test_proj_expansion_001'
        station_id = 'test_sta_link_001'

        conn.execute("""
            INSERT OR REPLACE INTO projects (
                entity_id, entity_type, canonical_name, country,
                capacity_mw, status, priority_tier, collection_priority, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (project_id_exp, 'project', 'Dam Expansion Project', 'CN', 1000.0, 'under_construction', 'B', 100))

        # 建立扩建关联
        link_id = linker.link_on_expansion(
            project_id=project_id_exp,
            station_id=station_id,
            expansion_date='2024-12-01',
            notes='增加1000MW容量'
        )
        print(f"[OK] 建立扩建关联: link_id={link_id}")

        # 创建改造项目
        project_id_upg = 'test_proj_upgrade_001'
        conn.execute("""
            INSERT OR REPLACE INTO projects (
                entity_id, entity_type, canonical_name, country,
                capacity_mw, status, priority_tier, collection_priority, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (project_id_upg, 'project', 'Dam Upgrade Project', 'CN', 0.0, 'approved', 'C', 200))

        # 建立改造关联
        link_id = linker.link_on_upgrade(
            project_id=project_id_upg,
            station_id=station_id,
            upgrade_date='2025-06-01',
            notes='机组现代化改造'
        )
        print(f"[OK] 建立改造关联: link_id={link_id}")

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


def test_query_station_projects():
    """测试查询电站的项目历史"""
    print("\n=== 测试 3: 查询电站的项目历史 ===")

    conn = connect()
    try:
        linker = ProjectStationLinker(conn)
        station_id = 'test_sta_link_001'

        # 查询项目历史
        projects = linker.get_station_projects(station_id)
        assert len(projects) >= 3, f"应有至少3个项目，实际{len(projects)}个"
        print(f"[OK] 电站 {station_id} 有 {len(projects)} 个关联项目")

        # 验证关联类型
        link_types = [p['link_type'] for p in projects]
        assert 'commissioning' in link_types, "应有投产关联"
        assert 'expansion' in link_types, "应有扩建关联"
        assert 'upgrade' in link_types, "应有改造关联"

        for p in projects:
            print(f"  - {p['canonical_name']}: {p['link_type']} ({p.get('effective_date', 'N/A')})")

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


def test_query_project_stations():
    """测试查询项目对应的电站"""
    print("\n=== 测试 4: 查询项目对应的电站 ===")

    conn = connect()
    try:
        linker = ProjectStationLinker(conn)
        project_id = 'test_proj_link_001'

        # 查询关联的电站
        stations = linker.get_project_stations(project_id)
        assert len(stations) >= 1, "应有至少1个电站"
        print(f"[OK] 项目 {project_id} 关联 {len(stations)} 个电站")

        for s in stations:
            print(f"  - {s['canonical_name']}: {s['link_type']} ({s.get('effective_date', 'N/A')})")

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


def test_remove_link():
    """测试删除关联"""
    print("\n=== 测试 5: 删除关联 ===")

    conn = connect()
    try:
        linker = ProjectStationLinker(conn)
        project_id = 'test_proj_upgrade_001'
        station_id = 'test_sta_link_001'

        # 删除改造关联
        deleted = linker.remove_link(project_id, station_id, 'upgrade')
        assert deleted > 0, "应删除至少1条记录"
        print(f"[OK] 删除了 {deleted} 条关联")

        # 验证已删除
        link = linker.get_link(project_id, station_id, 'upgrade')
        assert link is None, "关联应已删除"
        print("[OK] 关联已不存在")

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


def test_auto_link():
    """测试自动关联"""
    print("\n=== 测试 6: 自动关联（名称+年份匹配）===")

    conn = connect()
    try:
        linker = ProjectStationLinker(conn)

        # 先dry_run预览
        matches = linker.auto_link_by_name_and_year(dry_run=True)
        print(f"[OK] 预览找到 {len(matches)} 对匹配")

        if matches:
            for i, (proj, sta, conf) in enumerate(matches[:5], 1):
                print(f"  {i}. {proj} -> {sta} (confidence={conf})")

        # 实际执行自动关联（限制数量避免过多）
        if len(matches) > 0:
            # 清理已有的自动关联以便重新测试
            conn.execute("DELETE FROM project_station_links WHERE notes LIKE '%自动关联%'")
            conn.commit()

            matches_actual = linker.auto_link_by_name_and_year(dry_run=False)
            print(f"[OK] 实际创建了 {len(matches_actual)} 对关联")

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


def test_link_stats():
    """测试关联统计"""
    print("\n=== 测试 7: 关联统计 ===")

    conn = connect()
    try:
        linker = ProjectStationLinker(conn)

        stats = linker.get_link_stats()
        print(f"[OK] 关联统计:")
        print(f"  总关联数: {stats['links']['total']}")
        print(f"  投产: {stats['links']['commissioning']}")
        print(f"  扩建: {stats['links']['expansion']}")
        print(f"  改造: {stats['links']['upgrade']}")
        print(f"  关联项目数: {stats['linked_projects']}")
        print(f"  关联电站数: {stats['linked_stations']}")

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
    print("任务 3.3: Project-Station Linking 机制测试")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("投产关联", test_commissioning_link()))
    results.append(("扩建和改造关联", test_expansion_and_upgrade_links()))
    results.append(("查询电站的项目历史", test_query_station_projects()))
    results.append(("查询项目对应的电站", test_query_project_stations()))
    results.append(("删除关联", test_remove_link()))
    results.append(("自动关联", test_auto_link()))
    results.append(("关联统计", test_link_stats()))

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
        print("\n[OK] 任务 3.3 Project-Station Linking 机制实现完成")
        print("\n功能说明:")
        print("  - 支持3种关联类型: commissioning（投产）、expansion（扩建）、upgrade（改造）")
        print("  - 可查询电站的项目历史和项目对应的电站")
        print("  - 支持手动建立和删除关联")
        print("  - 支持自动关联（按名称+年份匹配）")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
