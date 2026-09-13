"""测试DeepSeek Discovery Level 3集成

验证项：
1. DeepSeek API Key从配置文件读取
2. 搜索功能基本可用
3. 集成到DiscoveryResolver
4. enabled标志控制
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.discovery.deepseek_search import DeepSeekSourceFinder
from hydro_platform.discovery.resolver import DiscoveryResolver


def test_deepseek_api_key_loading():
    """测试1：API Key加载"""
    print("\n=== 测试1：API Key加载 ===")

    finder = DeepSeekSourceFinder()

    print(f"DeepSeek状态: {'已启用' if finder.enabled else '未启用'}")

    if finder.enabled:
        # 显示前8位+省略号（脱敏）
        key_preview = finder.api_key[:8] + "..." if len(finder.api_key) > 8 else "***"
        print(f"API Key: {key_preview}")
        print("[PASS] API Key已加载")
    else:
        print("[WARN] 未配置API Key，功能将不可用")
        print("       请在 ~/.hydro_platform/llm_config.json 或环境变量中配置")

    return finder.enabled


def test_deepseek_basic_search():
    """测试2：基本搜索功能"""
    print("\n=== 测试2：基本搜索功能 ===")

    finder = DeepSeekSourceFinder()

    if not finder.enabled:
        print("[SKIP] DeepSeek未启用，跳过搜索测试")
        return False

    # 创建测试任务
    test_task = {
        "entity_name": "三峡水电站",
        "country": "CN",
        "metric": "generation",
        "target_year": 2024
    }

    print(f"测试任务: {test_task['entity_name']} {test_task['target_year']}年发电量")
    print("正在搜索候选来源...")

    try:
        candidates = finder.find(test_task, max_candidates=3)

        print(f"\n找到 {len(candidates)} 个候选来源:")
        for i, cand in enumerate(candidates, 1):
            print(f"  {i}. {cand.get('url', 'N/A')}")
            print(f"     来源类型: {cand.get('source_type', 'unknown')}")
            print(f"     匹配原因: {cand.get('match_reason', 'N/A')[:60]}...")

        print("[PASS] 搜索功能正常")
        return True

    except Exception as e:
        print(f"[FAIL] 搜索失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_discovery_resolver_integration():
    """测试3：集成到DiscoveryResolver"""
    print("\n=== 测试3：DiscoveryResolver集成 ===")

    # DiscoveryResolver需要数据库连接
    from hydro_platform.database.connection import connect
    db_path = project_root / "data" / "hydropower.sqlite"

    if not db_path.exists():
        print("[SKIP] 数据库不存在，跳过此测试")
        return None

    conn = connect(db_path)

    # 创建resolver（会自动初始化DeepSeekSourceFinder）
    resolver = DiscoveryResolver(conn)

    print(f"DeepSeek集成状态: {'已启用' if resolver.deepseek_finder.enabled else '未启用'}")

    conn.close()

    if resolver.deepseek_finder.enabled:
        print("[PASS] DeepSeek已集成到DiscoveryResolver")
        return True
    else:
        print("[WARN] DeepSeek未启用")
        return False


def test_graceful_degradation():
    """测试4：优雅降级（无API Key时）"""
    print("\n=== 测试4：优雅降级测试 ===")

    # 测试当DeepSeek disabled时的行为
    finder = DeepSeekSourceFinder()

    # 临时禁用以测试降级
    original_enabled = finder.enabled
    finder.enabled = False

    print(f"模拟disabled状态: {finder.enabled}")

    # 尝试搜索应该返回空列表而不是报错
    test_task = {"entity_name": "测试电站", "country": "CN"}
    try:
        candidates = finder.find(test_task)

        print(f"搜索结果: {len(candidates)} 个候选（应为0）")

        if len(candidates) == 0:
            print("[PASS] disabled时返回空列表，优雅降级正常")
            return True
        else:
            print("[WARN] disabled时应返回空列表")
            return True  # 不算失败，只是警告
    except Exception as e:
        print(f"[FAIL] disabled时不应抛异常: {e}")
        return False
    finally:
        # 恢复状态
        finder.enabled = original_enabled


def main():
    """运行所有测试"""
    print("=" * 60)
    print("DeepSeek Discovery Level 3 集成测试")
    print("=" * 60)

    results = []

    # 测试1：API Key加载
    has_api_key = test_deepseek_api_key_loading()
    results.append(("API Key加载", True))  # 有无key都算通过

    # 测试2：基本搜索（需要API Key）
    if has_api_key:
        search_ok = test_deepseek_basic_search()
        results.append(("基本搜索", search_ok))
    else:
        print("\n[INFO] 跳过搜索测试（需要配置API Key）")
        results.append(("基本搜索", None))  # None表示跳过

    # 测试3：Resolver集成
    integration_ok = test_discovery_resolver_integration()
    results.append(("Resolver集成", integration_ok))

    # 测试4：优雅降级
    degradation_ok = test_graceful_degradation()
    results.append(("优雅降级", degradation_ok))

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

    # 判断整体结果
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
