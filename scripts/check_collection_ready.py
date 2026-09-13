#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据采集准备状态检查脚本

检查系统是否准备好开始数据采集任务：
- 数据库连接
- 种子数据是否导入
- API 配置
- 目录结构
"""

import sys
from pathlib import Path
import sqlite3
import io

# 设置 stdout 为 UTF-8 编码（解决 Windows GBK 编码问题）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

def check_database():
    """检查数据库状态"""
    print("=" * 60)
    print("1. 检查数据库")
    print("=" * 60)

    db_path = Path("data/hydropower.sqlite")
    if not db_path.exists():
        print("❌ 数据库不存在: data/hydropower.sqlite")
        print("   请先运行: python -m hydro_platform.app.gui.main_window")
        return False

    print(f"✅ 数据库存在: {db_path}")

    # 检查表和数据
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查关键表
    tables = {
        'stations': '水电站种子数据',
        'generation_records': '发电量记录',
        'sources': '数据来源',
        'documents': '文档归档',
        'review_items': '待复核记录',
        'tasks': '采集任务'
    }

    print("\n表结构检查：")
    for table, desc in tables.items():
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  ✅ {table:20} {desc:15} {count:>6} 条")
        except sqlite3.OperationalError:
            print(f"  ❌ {table:20} 表不存在")

    # 检查 Top 100 电站
    cursor.execute("SELECT COUNT(*) FROM stations WHERE priority_tier = 'A'")
    top100_count = cursor.fetchone()[0]
    print(f"\n🎯 优先级 A 电站: {top100_count} 个")

    if top100_count == 0:
        print("⚠️  警告: 没有优先级 A 的电站，可能种子数据未正确导入")

    conn.close()
    return True


def check_directories():
    """检查目录结构"""
    print("\n" + "=" * 60)
    print("2. 检查目录结构")
    print("=" * 60)

    required_dirs = [
        "data/raw",
        "data/collection_tasks",
        "data/collection_tasks/downloads",
        "logs"
    ]

    all_ok = True
    for dir_path in required_dirs:
        p = Path(dir_path)
        if p.exists():
            print(f"  ✅ {dir_path}")
        else:
            print(f"  ❌ {dir_path} (不存在)")
            all_ok = False

    return all_ok


def check_api_config():
    """检查 API 配置"""
    print("\n" + "=" * 60)
    print("3. 检查 API 配置")
    print("=" * 60)

    import os

    # 检查 DeepSeek API Key
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        print(f"  ✅ DEEPSEEK_API_KEY: {deepseek_key[:8]}...{deepseek_key[-4:]}")
    else:
        print("  ⚠️  DEEPSEEK_API_KEY 未设置")
        print("     数据抽取步骤将无法使用 LLM")
        print("     设置方法:")
        print('       export DEEPSEEK_API_KEY="sk-..."  # Linux/Mac')
        print('       $env:DEEPSEEK_API_KEY="sk-..."   # Windows PowerShell')

    return deepseek_key is not None


def check_sample_stations():
    """显示示例电站"""
    print("\n" + "=" * 60)
    print("4. 示例电站（优先级 A）")
    print("=" * 60)

    db_path = Path("data/hydropower.sqlite")
    if not db_path.exists():
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT entity_id, canonical_name, country, capacity_mw,
               generation_status, priority_tier
        FROM stations
        WHERE priority_tier = 'A'
        ORDER BY capacity_mw DESC
        LIMIT 10
    """)

    print(f"\n{'序号':<4} {'电站名称':<35} {'国家':<10} {'容量(MW)':<10} {'数据状态':<12}")
    print("-" * 85)

    for i, row in enumerate(cursor.fetchall(), 1):
        entity_id, name, country, capacity, gen_status, tier = row
        status_icon = "✅" if gen_status == "complete" else "⏳"
        print(f"{i:<4} {name[:33]:<35} {country:<10} {capacity:>9.0f} {status_icon} {gen_status:<12}")

    conn.close()


def check_collection_tasks():
    """检查采集任务文件"""
    print("\n" + "=" * 60)
    print("5. 检查采集任务配置")
    print("=" * 60)

    task_files = [
        "data/collection_tasks/priority_sources.csv",
        "data/collection_tasks/DATA_COLLECTION_PLAN.md",
        "data/collection_tasks/MANUAL_IMPORT_GUIDE.md"
    ]

    for file_path in task_files:
        p = Path(file_path)
        if p.exists():
            size = p.stat().st_size
            print(f"  ✅ {p.name:40} ({size:>6} bytes)")
        else:
            print(f"  ❌ {p.name:40} (不存在)")


def print_next_steps():
    """打印下一步操作指南"""
    print("\n" + "=" * 60)
    print("📋 下一步操作指南")
    print("=" * 60)
    print("""
选项 1: 使用桌面应用手动导入（推荐）
  1. 启动应用: python -m hydro_platform.app.gui.main_window
  2. 点击「新增数据」
  3. 上传文件或添加 URL
  4. 等待处理完成
  5. 在「复核中心」审核结果

选项 2: 手动插入测试数据（快速验证）
  1. 阅读: data/collection_tasks/MANUAL_IMPORT_GUIDE.md
  2. 运行测试数据脚本（需要先创建）
  3. 打开桌面应用验证显示

选项 3: 查看详细采集计划
  1. 阅读: data/collection_tasks/DATA_COLLECTION_PLAN.md
  2. 浏览器访问已识别的数据源
  3. 手动下载 PDF/HTML 文档
  4. 批量导入

推荐流程（第一次）:
  ✅ 先手动导入 1-2 个电站测试流程
  ✅ 验证数据在桌面应用中正确显示
  ✅ 然后再考虑批量自动化
""")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("全球水电数据平台 - 数据采集准备状态检查")
    print("=" * 60 + "\n")

    # 执行检查
    db_ok = check_database()
    dir_ok = check_directories()
    api_ok = check_api_config()

    if db_ok:
        check_sample_stations()
        check_collection_tasks()

    # 总结
    print("\n" + "=" * 60)
    print("📊 检查总结")
    print("=" * 60)

    status = []
    status.append(("数据库", "✅" if db_ok else "❌"))
    status.append(("目录结构", "✅" if dir_ok else "❌"))
    status.append(("API配置", "✅" if api_ok else "⚠️"))

    for item, result in status:
        print(f"  {item:15} {result}")

    if db_ok and dir_ok:
        print("\n✅ 系统已准备好，可以开始数据采集！")
        print_next_steps()
    else:
        print("\n❌ 系统未准备好，请先解决上述问题")
        print("   提示: 首次运行需要初始化数据库和导入种子数据")

    return 0


if __name__ == "__main__":
    sys.exit(main())
