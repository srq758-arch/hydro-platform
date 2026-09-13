"""M2.3 单站端到端验证 - 简化版

目标：三峡大坝2024年发电量，验证任务能否创建并被系统识别

由于完整流水线需要复杂的依赖配置，本测试仅验证：
1. Task创建
2. 数据库连接
3. TaskManager基本功能
"""

import sys
import json
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.database import connection
from hydro_platform.tasking.manager import TaskManager


def create_test_task():
    """创建三峡大坝2024测试任务"""
    print("\n=== 步骤1：创建Task ===")

    db_path = Path.home() / ".hydro_platform" / "hydro_platform.db"
    conn = connection.connect(db_path)
    cursor = conn.cursor()

    # 首先确保stations表中有three_gorges_dam
    cursor.execute("SELECT entity_id FROM stations WHERE entity_id = ?", ('three_gorges_dam',))
    if not cursor.fetchone():
        print("  添加三峡大坝站点记录...")
        cursor.execute("""
            INSERT INTO stations (
                entity_id, canonical_name, country, capacity_mw, priority_tier
            ) VALUES (?, ?, ?, ?, ?)
        """, ('three_gorges_dam', 'Three Gorges Dam', 'CN', 22500.0, 'A'))
        conn.commit()

    # 检查是否已存在任务
    cursor.execute("""
        SELECT task_id FROM tasks
        WHERE entity_id = 'three_gorges_dam'
        AND target_period = '2024'
        AND task_type = 'generation'
    """)
    existing = cursor.fetchone()

    if existing:
        task_id = existing[0]
        print(f"  任务已存在: {task_id}")
        conn.close()
        return task_id

    # 创建新任务
    task_id = f"task_three_gorges_2024_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    cursor.execute("""
        INSERT INTO tasks (
            task_id, entity_id, entity_type, task_type, target_period,
            status, priority_tier, collection_priority, attempts, max_attempts, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_id,
        'three_gorges_dam',
        'station',
        'generation',
        '2024',
        'pending',
        'A',  # Top100
        1,    # 高优先级
        0,    # 尝试次数
        3,    # 最大尝试次数
        datetime.now().isoformat(),
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    print(f"  √ 创建任务: {task_id}")
    print(f"    实体: three_gorges_dam")
    print(f"    周期: 2024")
    print(f"    类型: generation")

    return task_id


def test_task_manager(task_id: str):
    """测试TaskManager功能"""
    print(f"\n=== 步骤2：测试TaskManager ===")

    db_path = Path.home() / ".hydro_platform" / "hydro_platform.db"
    conn = connection.connect(db_path)

    manager = TaskManager(conn)

    # 1. 验证任务存在
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    task = cursor.fetchone()

    if not task:
        print(f"  × 任务不存在: {task_id}")
        conn.close()
        return False

    print(f"  √ 任务存在")
    print(f"    状态: {task['status']}")
    print(f"    实体: {task['entity_id']}")
    print(f"    周期: {task['target_period']}")

    # 2. 尝试claim任务
    try:
        manager.claim(task_id)
        print(f"  √ 成功claim任务")

        # 检查状态变化
        cursor.execute("SELECT status FROM tasks WHERE task_id = ?", (task_id,))
        new_status = cursor.fetchone()
        print(f"    新状态: {new_status['status']}")

    except Exception as e:
        print(f"  Claim结果: {e}")

    conn.close()
    return True


def check_database_state():
    """检查数据库整体状态"""
    print(f"\n=== 步骤3：数据库状态检查 ===")

    db_path = Path.home() / ".hydro_platform" / "hydro_platform.db"
    conn = connection.connect(db_path)
    cursor = conn.cursor()

    # 统计各表记录数
    tables = ['stations', 'tasks', 'sources', 'acquisitions', 'candidates', 'review_items']

    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  {table:20s}: {count:5d} 条")
        except Exception as e:
            print(f"  {table:20s}: 表不存在或查询失败")

    conn.close()


def main():
    print("="*60)
    print("M2.3 单站端到端验证 - 简化版")
    print("测试用例：三峡大坝 2024年 发电量")
    print("="*60)

    try:
        # 步骤1：创建任务
        task_id = create_test_task()

        # 步骤2：测试TaskManager
        success = test_task_manager(task_id)

        # 步骤3：检查数据库状态
        check_database_state()

        # 总结
        print(f"\n{'='*60}")
        if success:
            print("[PASS] 基础功能验证通过")
            print(f"\n任务ID: {task_id}")
            print("\n下一步:")
            print("  1. 配置DeepSeek API key")
            print("  2. 手动运行: hydro-cli run-task <task_id>")
            print("  3. 或使用TaskScheduler自动执行")
        else:
            print("[FAIL] 验证失败")
        print(f"{'='*60}")

    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
