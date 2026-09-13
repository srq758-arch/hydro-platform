"""测试 Discovery 模块功能"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.database.connection import connect
from hydro_platform.discovery.official import OfficialSourceFinder
from hydro_platform.discovery.authority import AuthoritySourceFinder
from hydro_platform.discovery.resolver import DiscoveryResolver

def test_discovery():
    """测试 Discovery 模块"""

    print("=" * 60)
    print("测试 Discovery 模块")
    print("=" * 60)

    # 连接数据库
    db_path = project_root / "data" / "hydropower.sqlite"
    conn = connect(db_path)

    # 测试1: Official Source Finder
    print("\n[测试1] Official Source Finder")

    official_finder = OfficialSourceFinder(conn)

    # 使用真实电站测试
    task = {
        "entity_id": "GEM-G100000601208",  # 三峡大坝
        "entity_name": "Three Gorges Dam",
        "target_period": "2024",
        "metric": "generation"
    }

    candidates = official_finder.find(task)
    print(f"[OK] 找到 {len(candidates)} 个官方来源候选:")
    for i, cand in enumerate(candidates[:5], 1):
        print(f"  {i}. {cand.url}")
        print(f"     类型: {cand.source_type}, 文档: {cand.document_type}")

    assert len(candidates) > 0, "应该至少生成一些候选URL"
    print("[OK] Official Source Finder 测试通过")

    # 测试2: Authority Source Finder
    print("\n[测试2] Authority Source Finder")

    authority_finder = AuthoritySourceFinder(conn)

    # 测试中国电站
    task_china = {
        "entity_id": "GEM-G100000601208",
        "entity_name": "Three Gorges Dam",
        "target_period": "2024",
        "metric": "generation"
    }

    candidates_china = authority_finder.find(task_china)
    print(f"[OK] 中国电站找到 {len(candidates_china)} 个权威来源:")
    for cand in candidates_china:
        print(f"  - {cand.url} ({cand.match_reason})")

    # 测试美国电站（如果有）
    cursor = conn.execute("""
        SELECT entity_id, canonical_name
        FROM stations
        WHERE country = 'United States'
        LIMIT 1
    """)
    us_station = cursor.fetchone()

    if us_station:
        task_us = {
            "entity_id": us_station["entity_id"],
            "entity_name": us_station["canonical_name"],
            "target_period": "2024",
            "metric": "generation"
        }

        candidates_us = authority_finder.find(task_us)
        print(f"[OK] 美国电站找到 {len(candidates_us)} 个权威来源:")
        for cand in candidates_us:
            print(f"  - {cand.url} ({cand.match_reason})")

        assert any("eia.gov" in c.url for c in candidates_us), "美国电站应该返回EIA"

    print("[OK] Authority Source Finder 测试通过")

    # 测试3: Discovery Resolver（完整流程）
    print("\n[测试3] Discovery Resolver 完整流程")

    resolver = DiscoveryResolver(conn)

    task = {
        "entity_id": "GEM-G100000601208",
        "entity_name": "Three Gorges Dam",
        "target_period": "2024",
        "metric": "generation"
    }

    final_candidates = resolver.discover(task, min_candidates=3, max_candidates=10)

    print(f"\n[结果] Discovery 返回 {len(final_candidates)} 个候选:")
    for i, cand in enumerate(final_candidates[:5], 1):
        print(f"  {i}. {cand['url']}")
        print(f"     可靠性: {cand.get('source_reliability_score', 0):.2f}, "
              f"适配度: {cand.get('task_fit_score', 0):.2f}, "
              f"综合: {cand.get('combined_score', 0):.2f}")

    # 验证排序
    assert len(final_candidates) > 0, "应该找到候选来源"
    if len(final_candidates) > 1:
        # 验证排序正确性
        for i in range(len(final_candidates) - 1):
            score1 = final_candidates[i].get('combined_score', 0)
            score2 = final_candidates[i+1].get('combined_score', 0)
            assert score1 >= score2, f"排序错误: {score1} < {score2}"

    print("[OK] Discovery Resolver 测试通过")

    # 测试4: 验证年份匹配加分
    print("\n[测试4] 验证年份匹配逻辑")

    # 查找包含年份的URL
    urls_with_year = [c for c in final_candidates if '2024' in c['url']]
    print(f"[OK] {len(urls_with_year)} 个候选URL包含年份2024")

    if urls_with_year:
        for cand in urls_with_year[:3]:
            print(f"  - {cand['url']}")
            print(f"    适配度: {cand.get('task_fit_score', 0):.2f}")

    conn.close()

    print("\n" + "=" * 60)
    print("所有测试通过 [OK]")
    print("=" * 60)


if __name__ == "__main__":
    test_discovery()
