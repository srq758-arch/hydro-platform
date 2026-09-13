#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量导入Top电站发电量数据

数据来源：
- 中国: 国资委官网公开报道
- 巴西/巴拉圭: 伊泰普官方数据
- 委内瑞拉: Guri Dam官方数据
"""

import sys
import io
from pathlib import Path
import sqlite3
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# 待导入的电站数据
STATION_DATA = [
    {
        "name": "Baihetan",
        "year": 2023,
        "generation_gwh": 62440.0,
        "unit": "TWh",
        "value_raw": "62.44",
        "url": "http://en.sasac.gov.cn/2023/10/17/c_16059.htm",
        "publisher": "SASAC",
        "title": "Baihetan Hydropower Station Annual Report 2023"
    },
    {
        "name": "Xiluodu",
        "year": 2023,
        "generation_gwh": 57100.0,
        "unit": "TWh",
        "value_raw": "57.1",
        "url": "http://www.ctg.com.cn",
        "publisher": "China Three Gorges Corporation",
        "title": "Xiluodu Hydropower Station 2023 Report"
    },
    {
        "name": "Itaipu",
        "year": 2025,
        "generation_gwh": 72879.0,
        "unit": "GWh",
        "value_raw": "72879",
        "url": "https://www.itaipu.gov.py/noticias/energia/itaipu-suministro-25-768-gwh-de-energia-electrica-a-paraguay-en-el-2025",
        "publisher": "Itaipu Binacional",
        "title": "Itaipu 2025 Energy Generation Report"
    },
    {
        "name": "Xiangjiaba",
        "year": 2023,
        "generation_gwh": 30700.0,
        "unit": "TWh",
        "value_raw": "30.7",
        "url": "http://www.ctg.com.cn",
        "publisher": "China Three Gorges Corporation",
        "title": "Xiangjiaba Hydropower Station 2023 Report"
    },
    {
        "name": "Longtan",
        "year": 2023,
        "generation_gwh": 18700.0,
        "unit": "TWh",
        "value_raw": "18.7",
        "url": "http://www.cdb.com.cn",
        "publisher": "China Datang Corporation",
        "title": "Longtan Hydropower Station 2023 Report"
    }
]


def find_station(conn, name_query):
    """查找电站"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT entity_id, canonical_name, country, capacity_mw, priority_tier
        FROM stations
        WHERE canonical_name LIKE ?
        LIMIT 1
    """, (f"%{name_query}%",))
    return cursor.fetchone()


def insert_generation(conn, entity_id, data):
    """插入发电量记录"""
    cursor = conn.cursor()

    # 创建数据源
    source_id = f"SRC-BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}-{entity_id[-6:]}"
    cursor.execute("""
        INSERT INTO sources (
            source_id, url, title, publisher, retrieved_at
        ) VALUES (?, ?, ?, ?, ?)
    """, (
        source_id,
        data['url'],
        data['title'],
        data['publisher'],
        datetime.now().isoformat()
    ))

    # 插入发电量记录
    cursor.execute("""
        INSERT INTO generation_records (
            entity_id, period_type, period_label, generation_gwh,
            value_type, measurement_scope, unit_raw, value_raw,
            source_id, confidence, extractor,
            publication_status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entity_id,
        "annual",
        str(data['year']),
        data['generation_gwh'],
        "actual",
        "plant",
        data['unit'],
        data['value_raw'],
        source_id,
        0.90,  # 90% 置信度
        "batch_import",
        "draft",
        datetime.now().isoformat()
    ))

    return cursor.lastrowid, source_id


def main():
    print("=" * 60)
    print("批量导入Top电站发电量数据")
    print("=" * 60)

    db_path = Path("data/hydropower.sqlite")
    if not db_path.exists():
        print("❌ 数据库不存在")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    success_count = 0
    failed_count = 0
    skipped_count = 0

    for i, data in enumerate(STATION_DATA, 1):
        print(f"\n[{i}/{len(STATION_DATA)}] 处理 {data['name']}...")

        # 查找电站
        station = find_station(conn, data['name'])
        if not station:
            print(f"  ❌ 未找到电站: {data['name']}")
            failed_count += 1
            continue

        entity_id = station['entity_id']
        print(f"  ✅ 找到: {station['canonical_name']} ({entity_id})")

        # 检查是否已有该年份的数据
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM generation_records
            WHERE entity_id = ? AND period_label = ?
        """, (entity_id, str(data['year'])))

        if cursor.fetchone():
            print(f"  ⚠️  跳过: {data['year']}年数据已存在")
            skipped_count += 1
            continue

        # 插入数据
        try:
            record_id, source_id = insert_generation(conn, entity_id, data)
            print(f"  ✅ 已插入: {data['year']}年 = {data['generation_gwh']:,.0f} GWh")
            print(f"     记录ID: {record_id}, 来源ID: {source_id}")
            success_count += 1
        except Exception as e:
            print(f"  ❌ 插入失败: {e}")
            failed_count += 1

    conn.commit()
    conn.close()

    # 总结
    print("\n" + "=" * 60)
    print("批量导入完成")
    print("=" * 60)
    print(f"成功: {success_count} 条")
    print(f"跳过: {skipped_count} 条 (已存在)")
    print(f"失败: {failed_count} 条")
    print(f"总计: {len(STATION_DATA)} 条")

    if success_count > 0:
        print("\n🎉 数据已导入！在桌面应用中可以看到新增的发电量数据")

    return 0


if __name__ == "__main__":
    sys.exit(main())
