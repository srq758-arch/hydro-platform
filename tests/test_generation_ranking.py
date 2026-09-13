"""测试任务 5.1：Generation Ranking（Top 100 计算）

验证：
1. 基础排名计算
2. 国家过滤
3. 按国家分组排名
4. 统计信息
5. CSV导出
6. JSON导出
7. Markdown报告
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.products import GenerationRanking, RankingConfig
from hydro_platform.database.connection import connect
import tempfile
import json
import csv
import pytest


def setup_test_data(conn):
    """创建测试数据"""
    # 清理可能存在的测试数据（外键约束下的正确顺序）
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM generation_records WHERE entity_id LIKE 'sta_%'")
    conn.execute("DELETE FROM stations WHERE entity_id LIKE 'sta_%'")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()

    # 创建测试电站
    stations = [
        ('sta_001', 'Three Gorges Dam', 'CN', 22500.0),
        ('sta_002', 'Itaipu Dam', 'BR', 14000.0),
        ('sta_003', 'Xiluodu Dam', 'CN', 13860.0),
        ('sta_004', 'Guri Dam', 'VE', 10235.0),
        ('sta_005', 'Tucurui Dam', 'BR', 8370.0),
    ]

    for entity_id, name, country, capacity in stations:
        conn.execute("""
            INSERT OR REPLACE INTO stations (
                entity_id, entity_type, canonical_name, country,
                capacity_mw, priority_tier, collection_priority
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (entity_id, 'station', name, country, capacity, 'A', 100))

    # 创建测试发电记录
    records = [
    ('sta_001', '2023', 98800.0),  # Top 1
    ('sta_002', '2023', 89100.0),  # Top 2
        ('sta_003', '2023', 55620.0),  # Top 3
        ('sta_004', '2023', 53400.0),  # Top 4
        ('sta_005', '2023', 41200.0),  # Top 5
    ]

    for entity_id, period_label, generation in records:
        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_label, generation_gwh, unit_raw,
                period_type, value_type, measurement_scope,
                review_status, publication_status, validation_status,
                evidence_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            entity_id, period_label, generation, 'GWh',
            'calendar_year', 'actual', 'plant',
            'approved', 'publishable', 'passed',
            f'evidence_{entity_id}'
        ))

    conn.commit()


def test_basic_ranking(test_db):
    """测试基础排名计算"""
    print("\n=== 测试 1: 基础排名计算 ===")

    conn = test_db
    setup_test_data(conn)
    ranking = GenerationRanking(conn)

    # 计算 Top 5
    top5 = ranking.calculate_top_n(year=2023, limit=5)

    assert len(top5) == 5, f"应返回5条记录，实际{len(top5)}"
    assert top5[0]['rank'] == 1, "第一条应是排名1"
    assert top5[0]['canonical_name'] == 'Three Gorges Dam', "第一名应是三峡"
    assert top5[0]['generation_gwh'] == 98800.0, "发电量应匹配"

    print(f"[OK] 计算 Top 5:")
    for record in top5:
        print(f"  {record['rank']}. {record['canonical_name']}: {record['generation_gwh']:.2f} GWh")


def test_country_filtering(test_db):
    """测试国家过滤"""
    print("\n=== 测试 2: 国家过滤 ===")

    conn = test_db
    setup_test_data(conn)
    ranking = GenerationRanking(conn)

    # 仅查询中国电站
    cn_top = ranking.calculate_top_n(year=2023, limit=10, country='CN')

    assert len(cn_top) == 2, f"中国应有2个电站，实际{len(cn_top)}"
    assert all(r['country'] == 'CN' for r in cn_top), "所有记录应为中国"
    assert cn_top[0]['canonical_name'] == 'Three Gorges Dam', "中国第一应是三峡"

    print(f"[OK] 中国 Top {len(cn_top)}:")
    for record in cn_top:
        print(f"  {record['rank']}. {record['canonical_name']}: {record['generation_gwh']:.2f} GWh")

def test_ranking_by_country(test_db):
    """测试按国家分组排名"""
    print("\n=== 测试 3: 按国家分组排名 ===")

    conn = test_db
    setup_test_data(conn)
    ranking = GenerationRanking(conn)

    # 按国家分组计算 Top 10
    by_country = ranking.calculate_top_n_by_country(year=2023, limit_per_country=10)

    assert 'CN' in by_country, "应包含中国"
    assert 'BR' in by_country, "应包含巴西"
    assert len(by_country['CN']) == 2, "中国应有2个电站"
    assert len(by_country['BR']) == 2, "巴西应有2个电站"

    print(f"[OK] 按国家分组: {len(by_country)} 个国家")
    for country, records in by_country.items():
        print(f"  {country}: {len(records)} 个电站")


def test_statistics(test_db):
    """测试统计信息"""
    print("\n=== 测试 4: 统计信息 ===")

    conn = test_db
    setup_test_data(conn)
    ranking = GenerationRanking(conn)

    stats = ranking.get_statistics(year=2023)

    assert stats['total_records'] == 5, f"总记录数应为5，实际{stats['total_records']}"
    assert stats['total_stations'] == 5, f"电站数应为5，实际{stats['total_stations']}"
    assert stats['total_countries'] == 3, f"国家数应为3，实际{stats['total_countries']}"
    assert stats['total_generation_gwh'] > 0, "总发电量应>0"

    print(f"[OK] 统计信息:")
    print(f"  总记录数: {stats['total_records']}")
    print(f"  电站数: {stats['total_stations']}")
    print(f"  国家数: {stats['total_countries']}")
    print(f"  总发电量: {stats['total_generation_twh']:.2f} TWh")
    print(f"  平均发电量: {stats['avg_generation_gwh']:.2f} GWh")


def test_csv_export(test_db):
    """测试CSV导出"""
    print("\n=== 测试 5: CSV导出 ===")

    conn = test_db
    setup_test_data(conn)
    ranking = GenerationRanking(conn)

    # 导出到临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        temp_path = Path(f.name)

    ranking.export_to_csv(year=2023, output_path=temp_path, limit=5)

    # 验证文件存在
    assert temp_path.exists(), "CSV文件应已创建"

    # 读取验证
    with open(temp_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 5, f"应有5行数据，实际{len(rows)}"
    assert rows[0]['rank'] == '1', "第一行排名应为1"
    assert rows[0]['canonical_name'] == 'Three Gorges Dam', "第一名应是三峡"

    print(f"[OK] CSV导出成功: {temp_path}")
    print(f"  共 {len(rows)} 行")

    # 清理
    temp_path.unlink()


def test_json_export(test_db):
    """测试JSON导出"""
    print("\n=== 测试 6: JSON导出 ===")

    conn = test_db
    setup_test_data(conn)
    ranking = GenerationRanking(conn)

    # 导出到临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = Path(f.name)

    ranking.export_to_json(year=2023, output_path=temp_path, limit=5, include_stats=True)

    # 验证文件存在
    assert temp_path.exists(), "JSON文件应已创建"

    # 读取验证
    with open(temp_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    assert data['year'] == 2023, "年份应匹配"
    assert data['limit'] == 5, "限制数应匹配"
    assert data['count'] == 5, "实际数量应匹配"
    assert len(data['ranking']) == 5, "排名列表应有5条"
    assert 'statistics' in data, "应包含统计信息"

    print(f"[OK] JSON导出成功: {temp_path}")
    print(f"  年份: {data['year']}")
    print(f"  记录数: {data['count']}")
    print(f"  包含统计: {'statistics' in data}")

    # 清理
    temp_path.unlink()


def test_markdown_export(test_db):
    """测试Markdown导出"""
    print("\n=== 测试 7: Markdown报告导出 ===")

    conn = test_db
    setup_test_data(conn)
    ranking = GenerationRanking(conn)

    # 导出到临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        temp_path = Path(f.name)

    ranking.export_markdown_report(year=2023, output_path=temp_path, limit=5)

    # 验证文件存在
    assert temp_path.exists(), "Markdown文件应已创建"

    # 读取验证
    with open(temp_path, 'r', encoding='utf-8') as f:
        content = f.read()

    assert '# 全球水电站发电量 Top 5 (2023)' in content, "应包含标题"
    assert '## 统计摘要' in content, "应包含统计摘要"
    assert '## 排名' in content, "应包含排名表格"
    assert 'Three Gorges Dam' in content, "应包含三峡"

    print(f"[OK] Markdown报告导出成功: {temp_path}")
    print(f"  文件大小: {len(content)} 字节")

    # 清理
    temp_path.unlink()
        # 测试通过

    def test_config(test_db):
        """测试配置"""
    print("\n=== 测试 8: 配置 ===")

    default_limit = RankingConfig.get_default_limit()
    period_types = RankingConfig.get_supported_period_types()
    output_dir = RankingConfig.get_default_output_dir()

    print(f"[OK] 配置:")
    print(f"  默认限制: {default_limit}")
    print(f"  支持的统计口径: {', '.join(period_types)}")
    print(f"  默认输出目录: {output_dir}")

    return True


def main():
    print("=" * 60)
    print("任务 5.1: Generation Ranking（Top 100 计算）测试")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("基础排名计算", test_basic_ranking()))
    results.append(("国家过滤", test_country_filtering()))
    results.append(("按国家分组排名", test_ranking_by_country()))
    results.append(("统计信息", test_statistics()))
    results.append(("CSV导出", test_csv_export()))
    results.append(("JSON导出", test_json_export()))
    results.append(("Markdown报告", test_markdown_export()))
    results.append(("配置", test_config()))

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
        print("\n[OK] 任务 5.1 Generation Ranking 实现完成")
        print("\n功能说明:")
        print("  - 计算年度发电量 Top N 排名")
        print("  - 支持国家过滤和分组")
        print("  - 提供统计信息（总量、平均值等）")
        print("  - 导出为 CSV、JSON、Markdown 格式")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
