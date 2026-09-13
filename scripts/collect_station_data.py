#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据采集脚本 - 直接通过后端API收集电站数据

用法:
    python scripts/collect_station_data.py --station "Three Gorges" --file "path/to/document.txt"
    python scripts/collect_station_data.py --station "GEM-G100000601208" --url "http://example.com/report.pdf"
"""

import sys
import io
from pathlib import Path
import argparse
import sqlite3

# 设置 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from hydro_platform.pipeline.context import PipelineContext
from hydro_platform.acquisition.router import AcquisitionRouter
from hydro_platform.archive.archiver import Archiver
from hydro_platform.parsing.dispatcher import parse_document
from hydro_platform.extraction.llm.extractor import LLMExtractor
from hydro_platform.review.queue import ReviewQueue


def find_station(station_query: str) -> dict:
    """查找电站信息"""
    db_path = Path("data/hydropower.sqlite")
    if not db_path.exists():
        print("❌ 数据库不存在，请先初始化系统")
        return None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 尝试精确匹配 entity_id
    cursor.execute("SELECT * FROM stations WHERE entity_id = ?", (station_query,))
    row = cursor.fetchone()

    if not row:
        # 尝试模糊匹配名称
        cursor.execute("""
            SELECT * FROM stations
            WHERE canonical_name LIKE ? OR alternative_names LIKE ?
            LIMIT 5
        """, (f"%{station_query}%", f"%{station_query}%"))
        rows = cursor.fetchall()

        if not rows:
            print(f"❌ 未找到电站: {station_query}")
            conn.close()
            return None

        if len(rows) > 1:
            print(f"⚠️  找到多个匹配的电站，请选择:")
            for i, r in enumerate(rows, 1):
                print(f"  {i}. {r['canonical_name']} ({r['entity_id']}) - {r['country']} - {r['capacity_mw']} MW")

            choice = input("请输入编号 (1-5): ").strip()
            try:
                idx = int(choice) - 1
                row = rows[idx]
            except (ValueError, IndexError):
                print("❌ 无效的选择")
                conn.close()
                return None
        else:
            row = rows[0]

    station = dict(row)
    conn.close()

    print(f"✅ 找到电站: {station['canonical_name']} ({station['entity_id']})")
    print(f"   国家: {station['country']}, 容量: {station['capacity_mw']} MW")

    return station


def collect_from_file(station: dict, file_path: str):
    """从本地文件采集数据"""
    print(f"\n开始采集流程...")
    print(f"电站: {station['canonical_name']}")
    print(f"文件: {file_path}")

    file_path = Path(file_path)
    if not file_path.exists():
        print(f"❌ 文件不存在: {file_path}")
        return False

    # 1. 初始化上下文
    ctx = PipelineContext(
        task_type="manual_import",
        entity_id=station['entity_id'],
        db_path="data/hydropower.sqlite"
    )

    print("\n[1/5] 获取文档...")
    # 2. 采集 (直接读取本地文件)
    with open(file_path, 'rb') as f:
        content = f.read()

    mime_type = "text/plain" if file_path.suffix in ['.txt', '.md'] else "application/pdf"
    print(f"✅ 读取完成: {len(content)} bytes, 类型: {mime_type}")

    print("\n[2/5] 归档文档...")
    # 3. 归档
    archiver = Archiver(ctx)
    doc_id = archiver.archive(
        content=content,
        filename=file_path.name,
        mime_type=mime_type,
        source_url=f"file://{file_path.absolute()}"
    )
    print(f"✅ 归档完成: document_id = {doc_id}")

    print("\n[3/5] 解析文档...")
    # 4. 解析
    parsed = parse_document(ctx, doc_id)
    if not parsed or not parsed.get('text'):
        print("❌ 文档解析失败")
        return False

    text_preview = parsed['text'][:200].replace('\n', ' ')
    print(f"✅ 解析完成: {len(parsed['text'])} 字符")
    print(f"   预览: {text_preview}...")

    print("\n[4/5] 抽取数据...")
    # 5. 抽取
    candidates = extract_candidates(ctx, doc_id, parsed)

    if not candidates:
        print("⚠️  未抽取到候选记录")
        return False

    print(f"✅ 抽取完成: {len(candidates)} 条候选记录")
    for i, cand in enumerate(candidates, 1):
        print(f"   {i}. 年份: {cand.get('year')}, 发电量: {cand.get('generation_gwh')} GWh, 置信度: {cand.get('confidence')}")

    print("\n[5/5] 提交复核...")
    # 6. 进入复核队列
    review_mgr = ReviewManager(ctx.db_path)

    for cand in candidates:
        review_mgr.add_item(
            entity_id=station['entity_id'],
            year=cand['year'],
            generation_gwh=cand['generation_gwh'],
            source_id=doc_id,
            confidence=cand.get('confidence', 0.0),
            flags=cand.get('flags', []),
            evidence=cand.get('evidence', {})
        )

    print(f"✅ 已提交 {len(candidates)} 条记录到复核队列")
    print(f"\n🎉 采集完成！请在桌面应用的「复核中心」查看并审核数据")

    return True


def collect_from_url(station: dict, url: str):
    """从URL采集数据 (需要下载器)"""
    print(f"\n开始采集流程...")
    print(f"电站: {station['canonical_name']}")
    print(f"URL: {url}")

    # 1. 初始化上下文
    ctx = PipelineContext(
        task_type="url_import",
        entity_id=station['entity_id'],
        db_path="data/hydropower.sqlite"
    )

    print("\n[1/5] 下载文档...")
    # 2. 采集
    router = AcquisitionRouter(ctx)
    result = router.acquire(url)

    if not result or not result.get('content'):
        print("❌ 下载失败")
        return False

    print(f"✅ 下载完成: {len(result['content'])} bytes")

    print("\n[2/5] 归档文档...")
    # 3. 归档
    archiver = Archiver(ctx)
    doc_id = archiver.archive(
        content=result['content'],
        filename=result.get('filename', 'document'),
        mime_type=result.get('mime_type', 'text/html'),
        source_url=url
    )
    print(f"✅ 归档完成: document_id = {doc_id}")

    print("\n[3/5] 解析文档...")
    # 4. 解析
    parsed = parse_document(ctx, doc_id)
    if not parsed or not parsed.get('text'):
        print("❌ 文档解析失败")
        return False

    print(f"✅ 解析完成: {len(parsed['text'])} 字符")

    print("\n[4/5] 抽取数据...")
    # 5. 抽取
    candidates = extract_candidates(ctx, doc_id, parsed)

    if not candidates:
        print("⚠️  未抽取到候选记录")
        return False

    print(f"✅ 抽取完成: {len(candidates)} 条候选记录")

    print("\n[5/5] 提交复核...")
    # 6. 进入复核队列
    review_mgr = ReviewManager(ctx.db_path)

    for cand in candidates:
        review_mgr.add_item(
            entity_id=station['entity_id'],
            year=cand['year'],
            generation_gwh=cand['generation_gwh'],
            source_id=doc_id,
            confidence=cand.get('confidence', 0.0),
            flags=cand.get('flags', []),
            evidence=cand.get('evidence', {})
        )

    print(f"✅ 已提交 {len(candidates)} 条记录到复核队列")
    print(f"\n🎉 采集完成！请在桌面应用的「复核中心」查看并审核数据")

    return True


def main():
    parser = argparse.ArgumentParser(description="水电站数据采集脚本")
    parser.add_argument("--station", required=True, help="电站名称或 entity_id")
    parser.add_argument("--file", help="本地文件路径")
    parser.add_argument("--url", help="在线文档URL")

    args = parser.parse_args()

    if not args.file and not args.url:
        print("❌ 必须指定 --file 或 --url")
        return 1

    if args.file and args.url:
        print("❌ 不能同时指定 --file 和 --url")
        return 1

    print("=" * 60)
    print("水电数据采集脚本")
    print("=" * 60)

    # 查找电站
    station = find_station(args.station)
    if not station:
        return 1

    # 执行采集
    try:
        if args.file:
            success = collect_from_file(station, args.file)
        else:
            success = collect_from_url(station, args.url)

        return 0 if success else 1

    except Exception as e:
        print(f"\n❌ 采集失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
