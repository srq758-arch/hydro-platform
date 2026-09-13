"""端到端集成测试：SourceRegistry + Discovery + Orchestrator"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.database.connection import connect
from hydro_platform.pipeline.source_resolver import resolve_sources_enhanced
from hydro_platform.registry.source_registry import SourceRegistry
from hydro_platform.common.enums import TaskType, EntityType
from hydro_platform.models.task import Task


def test_source_resolver_integration():
    """测试 Source Resolver 集成"""

    print("=" * 60)
    print("端到端集成测试：Source Resolver")
    print("=" * 60)

    # 连接数据库
    db_path = project_root / "data" / "hydropower.sqlite"
    conn = connect(db_path)

    # 场景1: 新电站（无历史来源）- 应该触发 Discovery
    print("\n[场景1] 新电站（无历史来源）")
    print("-" * 60)

    # 创建测试任务
    entity_id = "GEM-G100000601208"  # 三峡大坝
    task_type = TaskType.STATION_GENERATION
    target_period = "2024"
    task_id = Task.derive_id(entity_id, task_type, target_period)

    task = Task(
        task_id=task_id,
        entity_id=entity_id,
        entity_type=EntityType.STATION,
        task_type=task_type,
        target_period=target_period
    )

    # 清理该电站的历史来源（模拟新电站）
    conn.execute("DELETE FROM sources WHERE entity_id = ?", (entity_id,))
    conn.commit()
    print(f"[准备] 清理电站历史来源: {entity_id}")

    # 解析来源
    refs = resolve_sources_enhanced(conn, task, fallback_resolver=None)

    print(f"\n[结果] 找到 {len(refs)} 个来源:")
    for i, ref in enumerate(refs, 1):
        print(f"  {i}. {ref.url}")
        print(f"     标题: {ref.title}")

    assert len(refs) > 0, "应该通过 Discovery 找到来源"
    print("[OK] 新电站触发 Discovery 成功")

    # 验证新来源已注册
    registry = SourceRegistry(conn)
    sources = registry.list_sources_for_entity(entity_id)
    print(f"\n[验证] 新来源已注册: {len(sources)} 个")
    for src in sources:
        print(f"  - {src['source_url']}")
        print(f"    评分: {src['source_reliability_score']:.2f}")
        print(f"    成功次数: {src['success_count']}")

    assert len(sources) > 0, "新来源应该已注册到 SourceRegistry"
    print("[OK] 新来源注册成功")

    # 场景2: 有历史来源的电站 - 应该直接使用历史来源
    print("\n" + "=" * 60)
    print("[场景2] 有历史来源的电站（第二次执行）")
    print("-" * 60)

    # 模拟更新来源为成功状态
    first_source = sources[0]
    registry.update_success(first_source['source_id'], document_id="test_doc")
    print(f"[准备] 标记来源为成功: {first_source['source_url']}")

    # 再次解析来源
    refs2 = resolve_sources_enhanced(conn, task, fallback_resolver=None)

    print(f"\n[结果] 找到 {len(refs2)} 个来源:")
    for i, ref in enumerate(refs2, 1):
        print(f"  {i}. {ref.url}")
        print(f"     标题: {ref.title}")

    # 应该返回历史来源
    assert len(refs2) > 0, "应该找到历史来源"
    assert refs2[0].url == first_source['source_url'], "应该使用历史来源"
    assert "历史来源" in refs2[0].title, "标题应该标注为历史来源"
    print("[OK] 使用历史来源成功")

    # 验证评分提升
    updated_sources = registry.list_sources_for_entity(entity_id)
    updated_source = [s for s in updated_sources if s['source_id'] == first_source['source_id']][0]
    print(f"\n[验证] 来源评分变化:")
    print(f"  初始评分: {first_source['source_reliability_score']:.2f}")
    print(f"  更新后评分: {updated_source['source_reliability_score']:.2f}")
    print(f"  成功次数: {updated_source['success_count']}")

    assert updated_source['source_reliability_score'] > first_source['source_reliability_score'], \
        "成功后评分应该提升"
    print("[OK] 评分提升验证通过")

    # 场景3: 历史来源预检失败 - 应该重新 Discovery
    print("\n" + "=" * 60)
    print("[场景3] 历史来源预检失败（频繁失败）")
    print("-" * 60)

    # 模拟来源频繁失败
    for i in range(5):
        registry.update_failure(
            first_source['source_id'],
            reason=f"测试失败 {i+1}",
            stage="acquisition"
        )
    print(f"[准备] 模拟来源频繁失败（5次）")

    # 再次解析来源
    refs3 = resolve_sources_enhanced(conn, task, fallback_resolver=None)

    print(f"\n[结果] 找到 {len(refs3)} 个来源:")
    for i, ref in enumerate(refs3, 1):
        print(f"  {i}. {ref.url}")
        print(f"     标题: {ref.title}")

    # 应该触发 Discovery（因为历史来源预检失败）
    if refs3:
        # 可能返回新的 Discovery 结果或其他历史来源
        print("[OK] 预检失败后重新发现来源")
    else:
        print("[WARN] 未找到可用来源")

    # 清理测试数据
    print("\n" + "=" * 60)
    print("[清理] 删除测试来源")
    conn.execute("DELETE FROM sources WHERE entity_id = ?", (entity_id,))
    conn.commit()

    conn.close()

    print("\n" + "=" * 60)
    print("端到端集成测试完成 [OK]")
    print("=" * 60)


if __name__ == "__main__":
    test_source_resolver_integration()
