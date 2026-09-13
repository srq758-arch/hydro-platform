"""测试任务调度器功能"""

import sys
import time
import threading
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.database.connection import connect
from hydro_platform.app.scheduler.task_scheduler import TaskScheduler
from hydro_platform.database.repositories import TaskRepository
from hydro_platform.common.enums import TaskStatus, TaskType, EntityType
from hydro_platform.models.task import Task

def mock_task_executor(task_id: str):
    """模拟任务执行函数"""
    print(f"  [Worker] 开始执行任务: {task_id}")
    time.sleep(2)  # 模拟工作
    print(f"  [Worker] 任务完成: {task_id}")
    return {"status": "success", "task_id": task_id}

def test_task_scheduler():
    """测试任务调度器"""

    print("=" * 60)
    print("测试 TaskScheduler")
    print("=" * 60)

    # 连接数据库
    db_path = project_root / "data" / "hydropower.sqlite"
    conn = connect(db_path)

    # 清理测试任务
    print("\n[准备] 清理旧的测试任务")
    conn.execute("DELETE FROM tasks WHERE entity_id LIKE 'test_scheduler_%'")
    conn.commit()

    # 创建测试任务
    print("\n[准备] 创建3个测试任务")
    task_repo = TaskRepository(conn)

    tasks = []
    for i in range(3):
        entity_id = f"test_scheduler_{i:03d}"
        task_type = TaskType.STATION_GENERATION
        target_period = "2024"

        task_id = Task.derive_id(entity_id, task_type, target_period)

        task = Task(
            task_id=task_id,
            entity_id=entity_id,
            entity_type=EntityType.STATION,
            task_type=task_type,
            target_period=target_period,
            status=TaskStatus.PENDING
        )
        tasks.append(task)

    task_repo.upsert_many(tasks)
    conn.commit()
    print(f"[OK] 创建了 {len(tasks)} 个 pending 任务")

    # 完成和错误回调
    completed_tasks = []
    failed_tasks = []

    def on_complete(task_id, result):
        print(f"  [Callback] 任务完成回调: {task_id}")
        completed_tasks.append(task_id)

    def on_error(task_id, error):
        print(f"  [Callback] 任务错误回调: {task_id} - {error}")
        failed_tasks.append(task_id)

    # 创建调度器
    print("\n[测试1] 启动调度器")
    scheduler = TaskScheduler(
        db_path=str(db_path),
        task_executor=mock_task_executor,
        max_workers=2,
        scan_interval=3,
        on_task_complete=on_complete,
        on_task_error=on_error
    )

    scheduler.start()
    print("[OK] 调度器已启动")

    # 检查状态
    status = scheduler.get_status()
    print(f"  - 运行中: {status['running']}")
    print(f"  - 最大并发: {status['max_workers']}")
    print(f"  - 扫描间隔: {status['scan_interval']}s")

    # 等待任务执行
    print("\n[测试2] 等待任务自动执行（约15秒）...")
    max_wait = 30
    start_time = time.time()

    while len(completed_tasks) < 3 and (time.time() - start_time) < max_wait:
        time.sleep(2)
        status = scheduler.get_status()
        print(f"  进度: {len(completed_tasks)}/3 完成, "
              f"{status['active_workers']} workers 活跃")

    # 检查结果
    print(f"\n[结果] 完成 {len(completed_tasks)}/3 任务")
    print(f"  - 完成: {completed_tasks}")
    print(f"  - 失败: {failed_tasks}")

    if len(completed_tasks) >= 2:
        print("[OK] 调度器成功执行任务")
    else:
        print("[WARN] 部分任务未完成")

    # 测试暂停/恢复
    print("\n[测试3] 测试暂停/恢复")
    scheduler.pause()
    status = scheduler.get_status()
    print(f"  暂停后状态: paused={status['paused']}")
    assert status['paused'] == True

    scheduler.resume()
    status = scheduler.get_status()
    print(f"  恢复后状态: paused={status['paused']}")
    assert status['paused'] == False
    print("[OK] 暂停/恢复功能正常")

    # 停止调度器
    print("\n[测试4] 停止调度器")
    scheduler.stop()
    status = scheduler.get_status()
    print(f"  停止后状态: running={status['running']}")
    assert status['running'] == False
    print("[OK] 调度器已停止")

    # 检查数据库中的任务状态
    print("\n[验证] 检查任务最终状态")
    conn = connect(db_path)
    cursor = conn.execute("""
        SELECT status, COUNT(*) as cnt
        FROM tasks
        WHERE entity_id LIKE 'test_scheduler_%'
        GROUP BY status
    """)

    for row in cursor:
        print(f"  {row['status']}: {row['cnt']}")

    conn.close()

    print("\n" + "=" * 60)
    print("测试完成 [OK]")
    print("=" * 60)


if __name__ == "__main__":
    test_task_scheduler()
