"""测试DeepSeek Discovery Level 3

测试DeepSeek智能搜索功能：
1. 推理阶段：智能生成URL
2. 搜索阶段：联网查找真实文档
3. 集成测试：完整Discovery流程
"""

import sys
from pathlib import Path
import os

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.discovery.deepseek_search import DeepSeekSourceFinder
from hydro_platform.discovery.resolver import DiscoveryResolver
from hydro_platform.database.connection import connect


def test_deepseek_finder():
    """测试DeepSeek Finder基础功能"""
    print("=" * 60)
    print("测试1: DeepSeek Finder基础功能")
    print("=" * 60)

    # 检查API Key
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("\n[警告] 未设置DEEPSEEK_API_KEY环境变量")
        print("请设置: export DEEPSEEK_API_KEY=your_key")
        print("\n跳过DeepSeek测试")
        return False

    print(f"\n[OK] API Key已设置: {api_key[:10]}...")

    # 创建Finder
    finder = DeepSeekSourceFinder(api_key=api_key)

    if not finder.enabled:
        print("[FAIL] DeepSeek未启用")
        return False

    print("[OK] DeepSeek已启用")

    # 测试用例：三峡大坝
    task = {
        "entity_id": "CHN_three_gorges_dam",
        "entity_name": "Three Gorges Dam",
        "target_period": "2024",
        "metric": "generation",
        "country": "China"
    }

    print(f"\n测试任务:")
    print(f"  电站: {task['entity_name']}")
    print(f"  年份: {task['target_period']}")
    print(f"  指标: {task['metric']}")

    # 执行搜索
    print("\n开始DeepSeek搜索...")
    try:
        candidates = finder.find(task, max_candidates=5)

        print(f"\n[OK] 找到 {len(candidates)} 个候选\n")

        for i, candidate in enumerate(candidates, 1):
            print(f"候选 {i}:")
            print(f"  URL: {candidate['url']}")
            print(f"  类型: {candidate['source_type']}")
            print(f"  文档: {candidate['document_type']}")
            print(f"  方法: {candidate['discovery_method']}")
            if candidate.get('title'):
                print(f"  标题: {candidate['title']}")
            if candidate['metadata'].get('reasoning'):
                print(f"  理由: {candidate['metadata']['reasoning'][:100]}...")
            print()

        return len(candidates) > 0

    except Exception as e:
        print(f"\n[FAIL] DeepSeek搜索失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_discovery_integration():
    """测试Discovery集成"""
    print("\n" + "=" * 60)
    print("测试2: Discovery完整集成（Level 1-2-3）")
    print("=" * 60)

    # 检查API Key
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("\n[跳过] 未设置DEEPSEEK_API_KEY")
        return True

    # 连接数据库
    db_path = project_root / "data" / "hydropower.sqlite"
    conn = connect(db_path)

    # 创建Resolver（传入API Key）
    resolver = DiscoveryResolver(conn, deepseek_api_key=api_key)

    # 测试场景：Level 1-2找不到足够候选，触发Level 3
    task = {
        "entity_id": "test_unknown_station",
        "entity_name": "Unknown Hydropower Plant",
        "target_period": "2024",
        "metric": "generation",
        "country": "Unknown"
    }

    print(f"\n测试场景: Level 1-2候选不足，应触发Level 3")
    print(f"  电站: {task['entity_name']}")

    try:
        # 设置min_candidates=8，确保会触发Level 3
        candidates = resolver.discover(task, min_candidates=8, max_candidates=10)

        print(f"\n[OK] Discovery完成，找到 {len(candidates)} 个候选\n")

        # 统计各级别候选数
        level_stats = {}
        for candidate in candidates:
            method = candidate.get('discovery_method', candidate.get('source_type', 'unknown'))
            level_stats[method] = level_stats.get(method, 0) + 1

        print("各级别贡献:")
        for method, count in level_stats.items():
            print(f"  {method}: {count}")

        # 显示Top 5
        print("\nTop 5 候选:")
        for i, candidate in enumerate(candidates[:5], 1):
            print(f"  {i}. {candidate['url']}")
            print(f"     评分: {candidate.get('combined_score', 0):.3f}")
            print(f"     来源: {candidate.get('discovery_method', candidate.get('source_type'))}")

        conn.close()
        return True

    except Exception as e:
        print(f"\n[FAIL] Discovery集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        conn.close()
        return False


def test_real_station():
    """测试真实电站场景"""
    print("\n" + "=" * 60)
    print("测试3: 真实电站场景")
    print("=" * 60)

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("\n[跳过] 未设置DEEPSEEK_API_KEY")
        return True

    db_path = project_root / "data" / "hydropower.sqlite"
    conn = connect(db_path)

    # 查询一个真实电站
    cursor = conn.execute("""
        SELECT entity_id, canonical_name, country
        FROM stations
        WHERE country = 'China'
        AND official_website IS NULL
        LIMIT 1
    """)
    station = cursor.fetchone()

    if not station:
        print("[跳过] 未找到合适的测试电站")
        conn.close()
        return True

    task = {
        "entity_id": station["entity_id"],
        "entity_name": station["canonical_name"],
        "target_period": "2023",
        "metric": "generation",
        "country": station["country"]
    }

    print(f"\n测试电站: {task['entity_name']}")
    print(f"  国家: {task['country']}")
    print(f"  无官方网站（Level 1会失败）")

    resolver = DiscoveryResolver(conn, deepseek_api_key=api_key)

    try:
        candidates = resolver.discover(task, min_candidates=3, max_candidates=10)

        print(f"\n[OK] 找到 {len(candidates)} 个候选")

        if candidates:
            print("\n最佳候选:")
            best = candidates[0]
            print(f"  URL: {best['url']}")
            print(f"  评分: {best.get('combined_score', 0):.3f}")
            print(f"  类型: {best['source_type']}")

        conn.close()
        return len(candidates) > 0

    except Exception as e:
        print(f"\n[FAIL] 真实场景测试失败: {e}")
        conn.close()
        return False


if __name__ == "__main__":
    print("DeepSeek Discovery Level 3 测试")
    print("=" * 60)

    results = []

    # 测试1: 基础功能
    results.append(("DeepSeek Finder", test_deepseek_finder()))

    # 测试2: Discovery集成
    results.append(("Discovery集成", test_discovery_integration()))

    # 测试3: 真实场景
    results.append(("真实电站场景", test_real_station()))

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "[OK]" if result else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\n通过率: {passed}/{total} ({passed/total*100:.1f}%)")

    if passed == total:
        print("\n所有测试通过 ✓")
    else:
        print(f"\n{total - passed} 个测试失败")
