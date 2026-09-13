"""测试 SourceRegistry 基本功能"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.database.connection import connect
from hydro_platform.registry.source_registry import SourceRegistry

def test_source_registry():
    """测试 SourceRegistry 基本功能"""

    print("=" * 60)
    print("测试 SourceRegistry")
    print("=" * 60)

    # 连接数据库
    db_path = project_root / "data" / "hydropower.sqlite"
    conn = connect(db_path)

    registry = SourceRegistry(conn)

    # 测试1: 注册新来源
    print("\n[测试1] 注册新来源")
    source_id = registry.register_new_source(
        entity_id="test_station_001",
        source_url="https://example.com/annual-report-2024.pdf",
        metadata={
            "source_type": "official",
            "document_type": "pdf",
            "covered_metric": "generation",
            "covered_year": 2024,
            "access_method": "http",
            "match_reason": "测试注册",
            "estimated_reliability": 0.85
        }
    )
    print(f"[OK] 注册成功: {source_id}")

    # 测试2: 查询历史来源
    print("\n[测试2] 查询历史来源")
    source = registry.query_best_source(
        entity_id="test_station_001",
        metric="generation",
        year=2024
    )

    if source:
        print(f"[OK] 找到来源:")
        print(f"  - URL: {source['source_url']}")
        print(f"  - 评分: {source['source_reliability_score']:.2f}")
        print(f"  - 类型: {source['source_type']}")
    else:
        print("[FAIL] 未找到来源")

    # 测试3: 更新成功记录
    print("\n[测试3] 更新成功记录")
    registry.update_success(source_id, document_id="doc_001")
    print(f"[OK] 成功记录已更新")

    # 测试4: 再次查询，验证评分提升
    print("\n[测试4] 验证评分提升")
    source_updated = registry.query_best_source(
        entity_id="test_station_001",
        metric="generation",
        year=2024
    )

    if source_updated:
        print(f"[OK] 更新后评分: {source_updated['source_reliability_score']:.2f}")
        print(f"  成功次数: {source_updated['success_count']}")

    # 测试5: 更新失败记录
    print("\n[测试5] 更新失败记录")
    registry.update_failure(source_id, reason="测试失败", stage="acquisition")
    print(f"[OK] 失败记录已更新")

    # 测试6: 列出所有来源
    print("\n[测试6] 列出电站所有来源")
    sources = registry.list_sources_for_entity("test_station_001")
    print(f"[OK] 找到 {len(sources)} 个来源:")
    for src in sources:
        print(f"  - {src['source_url']} (评分: {src['source_reliability_score']:.2f})")

    conn.close()

    print("\n" + "=" * 60)
    print("测试完成 [OK]")
    print("=" * 60)


if __name__ == "__main__":
    test_source_registry()
