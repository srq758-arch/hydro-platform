#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简易数据采集脚本 - 直接插入测试数据

用法:
    python scripts/simple_collect.py
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
    print("水电站数据采集 - 简易版")
    print("=" * 60)

    db_path = Path("data/hydropower.sqlite")
    if not db_path.exists():
        print("❌ 数据库不存在")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. 查找三峡大坝
    print("\n[1/4] 查找电站...")
    cursor.execute("""
        SELECT entity_id, canonical_name, country, capacity_mw, priority_tier
        FROM stations
        WHERE canonical_name LIKE '%Three Gorges%'
    """)
    station = cursor.fetchone()

    if not station:
        print("❌ 未找到三峡大坝")
        return 1

    print(f"✅ 找到: {station['canonical_name']} ({station['entity_id']})")
    print(f"   容量: {station['capacity_mw']} MW, 优先级: {station['priority_tier']}")

    # 2. 创建数据源记录
    print("\n[2/4] 创建数据源...")
    cursor.execute("""
        INSERT INTO sources (
            source_id, entity_id, source_type, url, retrieved_at,
            content_kind, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "SRC-TEST-001",
        station['entity_id'],
        "official_report",
        "http://en.sasac.gov.cn/2025/09/09/c_19816.htm",
        datetime.now().isoformat(),
        "html",
        "fetched"
    ))
    print("✅ 数据源已创建: SRC-TEST-001")

    # 3. 创建归档文档记录
    print("\n[3/4] 创建归档记录...")
    cursor.execute("""
        INSERT INTO documents (
            doc_id, source_id, entity_id, mime_type,
            local_path, archived_at, file_size
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "DOC-TEST-001",
        "SRC-TEST-001",
        station['entity_id'],
        "text/plain",
        "data/collection_tasks/downloads/test_three_gorges_2024.txt",
        datetime.now().isoformat(),
        1024
    ))
    print("✅ 文档已归档: DOC-TEST-001")

    # 4. 插入待复核记录
    print("\n[4/4] 创建复核记录...")
    cursor.execute("""
        INSERT INTO review_items (
            entity_id, year, generation_gwh, source_id,
            confidence, extracted_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        station['entity_id'],
        2024,
        103000.0,  # 103 TWh = 103,000 GWh
        "SRC-TEST-001",
        0.95,
        datetime.now().isoformat(),
        "pending"
    ))

    review_id = cursor.lastrowid
    print(f"✅ 复核记录已创建: ID = {review_id}")
    print(f"   年份: 2024")
    print(f"   发电量: 103,000 GWh (103 TWh)")
    print(f"   置信度: 95%")

    conn.commit()
    conn.close()

    print("\n" + "=" * 60)
    print("🎉 数据采集完成！")
    print("=" * 60)
    print("\n下一步:")
    print("1. 在桌面应用中打开「复核中心」页面")
    print("2. 你会看到一条待审核的记录")
    print("3. 点击「批准」即可发布到正式数据库")
    print("\n或者运行:")
    print("  python scripts/approve_review.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
