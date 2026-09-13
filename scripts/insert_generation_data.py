#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简易数据采集脚本 - 直接插入发电量数据到数据库

用法:
    python scripts/insert_generation_data.py
"""

import sys
import io
from pathlib import Path
import sqlite3
from datetime import datetime

# 设置 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    print("=" * 60)
    print("水电站发电量数据采集")
    print("=" * 60)

    db_path = Path("data/hydropower.sqlite")
    if not db_path.exists():
        print("❌ 数据库不存在")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. 查找三峡大坝
    print("\n[1/3] 查找电站...")
    cursor.execute("""
        SELECT entity_id, canonical_name, country, capacity_mw, priority_tier
        FROM stations
        WHERE canonical_name LIKE '%Three Gorges%'
    """)
    station = cursor.fetchone()

    if not station:
        print("❌ 未找到三峡大坝")
        conn.close()
        return 1

    entity_id = station['entity_id']
    print(f"✅ 找到: {station['canonical_name']}")
    print(f"   ID: {entity_id}")
    print(f"   容量: {station['capacity_mw']} MW")
    print(f"   优先级: {station['priority_tier']}")

    # 2. 创建数据源记录
    print("\n[2/3] 创建数据源...")
    source_id = f"SRC-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    cursor.execute("""
        INSERT INTO sources (
            source_id, url, title, publisher, retrieved_at
        ) VALUES (?, ?, ?, ?, ?)
    """, (
        source_id,
        "http://en.sasac.gov.cn/2025/09/09/c_19816.htm",
        "Three Gorges Dam 2024 Generation Report",
        "State-owned Assets Supervision and Administration Commission",
        datetime.now().isoformat()
    ))
    print(f"✅ 数据源已创建: {source_id}")

    # 3. 插入发电量记录
    print("\n[3/3] 插入发电量数据...")

    # 插入2024年的数据
    cursor.execute("""
        INSERT INTO generation_records (
            entity_id, period_type, period_label, generation_gwh,
            value_type, measurement_scope, unit_raw, value_raw,
            source_id, confidence, extractor,
            publication_status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entity_id,
        "annual",           # 年度数据
        "2024",            # 2024年
        103000.0,          # 103 TWh = 103,000 GWh
        "actual",          # 实际值
        "plant",           # 电站级别
        "TWh",             # 原始单位
        "103.0",           # 原始值
        source_id,         # 数据源ID
        0.95,              # 置信度95%
        "manual",          # 手动导入
        "draft",           # 草稿状态（需要复核）
        datetime.now().isoformat()
    ))

    record_id = cursor.lastrowid
    print(f"✅ 发电量记录已创建: ID = {record_id}")
    print(f"   年份: 2024")
    print(f"   发电量: 103,000 GWh (103 TWh)")
    print(f"   置信度: 95%")
    print(f"   状态: draft (待复核)")

    conn.commit()

    # 4. 验证插入
    print("\n验证数据...")
    cursor.execute("""
        SELECT g.*, s.url, s.publisher
        FROM generation_records g
        LEFT JOIN sources s ON g.source_id = s.source_id
        WHERE g.entity_id = ? AND g.period_label = '2024'
    """, (entity_id,))

    record = cursor.fetchone()
    if record:
        print(f"✅ 数据验证成功:")
        print(f"   电站: {entity_id}")
        print(f"   年份: {record['period_label']}")
        print(f"   发电量: {record['generation_gwh']:,.0f} GWh")
        print(f"   数据源: {record['url']}")
        print(f"   发布机构: {record['publisher']}")

    conn.close()

    print("\n" + "=" * 60)
    print("🎉 数据采集完成！")
    print("=" * 60)
    print("\n下一步:")
    print("1. 刷新桌面应用")
    print("2. 在「电站列表」中搜索 'Three Gorges'")
    print("3. 点击电站名称查看详情")
    print("4. 应该能看到2024年的发电量数据 (103,000 GWh)")
    print("\n或者查询数据库:")
    print(f"  sqlite3 data/hydropower.sqlite")
    print(f"  SELECT * FROM generation_records WHERE entity_id='{entity_id}';")

    return 0


if __name__ == "__main__":
    sys.exit(main())
