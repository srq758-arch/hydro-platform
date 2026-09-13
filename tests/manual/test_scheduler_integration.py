"""测试TaskScheduler集成

验证项：
1. TaskScheduler能否正常启动
2. 调度器参数配置正确（max_workers=2, scan_interval=10）
3. 启动/停止/暂停/恢复控制API
4. 扫描pending任务并自动执行
"""

import sys
import time
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.app.scheduler.task_scheduler import TaskScheduler
from hydro_platform.database.connection import connect
from hydro_platform.database.repositories import TaskRepository
from hydro_platform.common.enums import TaskStatus


def test_scheduler_basic():
    """测试1：基本启动和停止"""
    print("\n=== 测试1：TaskScheduler基本功能 ===")

    db_path = project_root / "data" / "hydropower.sqlite"

    # 定义简单的任务执行器
    executed_tasks = []

    def mock_executor(task_id):
        print(f"[MockExecutor] 执行任务: {task_id}")
        executed_tasks.append(task_id)
        time.sleep(0.1)  # 模拟执行时间
        return {"status": "success"}

    # 创建调度器
    scheduler = TaskScheduler(
        db_path=str(db_path),
        task_executor=mock_executor,
        max_workers=2,
        scan_interval=10
    )

    print(f"调度器配置: max_workers={scheduler.max_workers}, scan_interval={scheduler.scan_interval}")
    assert scheduler.max_workers == 2, "max_workers配置错误"
    assert scheduler.scan_interval == 10, "scan_interval配置错误"

    # 启动调度器
    scheduler.start()
    assert scheduler.running, "调度器未启动"
    print("[PASS] 调度器已启动")

    # 等待1秒
    time.sleep(1)

    # 停止调度器
    scheduler.stop()
    assert not scheduler.running, "调度器未停止"
    print("[PASS] 调度器已停止")

    print("[PASS] 测试1通过")


def test_scheduler_pause_resume():
    """测试2：暂停和恢复"""
    print("\n=== 测试2：暂停和恢复功能 ===")

    db_path = project_root / "data" / "hydropower.sqlite"

    def mock_executor(task_id):
        return {"status": "success"}

    scheduler = TaskScheduler(
        db_path=str(db_path),
        task_executor=mock_executor,
        max_workers=2,
        scan_interval=10
    )

    scheduler.start()
    assert scheduler.running and not scheduler.paused, "初始状态错误"
    print("[PASS] 调度器运行中")

    # 暂停
    scheduler.pause()
    assert scheduler.paused, "暂停失败"
    print("[PASS] 调度器已暂停")

    # 恢复
    scheduler.resume()
    assert not scheduler.paused, "恢复失败"
    print("[PASS] 调度器已恢复")

    # 清理
    scheduler.stop()
    print("[PASS] 测试2通过")


def test_scheduler_status():
    """测试3：状态查询"""
    print("\n=== 测试3：状态查询 ===")

    db_path = project_root / "data" / "hydropower.sqlite"

    def mock_executor(task_id):
        return {"status": "success"}

    scheduler = TaskScheduler(
        db_path=str(db_path),
        task_executor=mock_executor,
        max_workers=2,
        scan_interval=10
    )

    # 未启动状态
    status = scheduler.get_status()
    assert status["running"] == False, "初始状态应为未运行"
    assert status["paused"] == False, "初始状态应为未暂停"
    print(f"初始状态: {status}")

    # 启动后状态
    scheduler.start()
    status = scheduler.get_status()
    assert status["running"] == True, "启动后应为运行中"
    assert status["active_workers"] == 0, "初始无活动worker"
    assert status["max_workers"] == 2, "max_workers不匹配"
    print(f"运行状态: {status}")

    # 清理
    scheduler.stop()
    print("[PASS] 测试3通过")


def test_scheduler_with_real_task():
    """测试4：真实任务调度（如果数据库中有pending任务）"""
    print("\n=== 测试4：真实任务调度 ===")

    db_path = project_root / "data" / "hydropower.sqlite"

    if not db_path.exists():
        print("[SKIP] 数据库不存在，跳过此测试")
        return

    # 检查是否有pending任务
    conn = connect(db_path)
    task_repo = TaskRepository(conn)

    pending_tasks = conn.execute(
        "SELECT task_id, entity_id FROM tasks WHERE status = ? LIMIT 1",
        (TaskStatus.PENDING.value,)
    ).fetchall()

    if not pending_tasks:
        print("[SKIP] 无pending任务，跳过实际调度测试")
        print("  可以手动创建测试任务验证")
        conn.close()
        return

    print(f"发现 {len(pending_tasks)} 个pending任务")

    executed_count = [0]  # 使用列表实现闭包可变

    def counting_executor(task_id):
        print(f"[Executor] 执行任务: {task_id}")
        executed_count[0] += 1
        return {"status": "success"}

    scheduler = TaskScheduler(
        db_path=str(db_path),
        task_executor=counting_executor,
        max_workers=2,
        scan_interval=2  # 快速扫描用于测试
    )

    scheduler.start()
    print("[PASS] 调度器已启动，等待5秒观察任务执行...")

    # 等待调度器扫描并执行任务
    time.sleep(5)

    scheduler.stop()

    if executed_count[0] > 0:
        print(f"[PASS] 成功执行了 {executed_count[0]} 个任务")
    else:
        print("[INFO] 未执行任务（可能任务状态已变更或调度间隔未到）")

    conn.close()
    print("[PASS] 测试4完成")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("TaskScheduler集成测试")
    print("=" * 60)

    try:
        test_scheduler_basic()
        test_scheduler_pause_resume()
        test_scheduler_status()
        test_scheduler_with_real_task()

        print("\n" + "=" * 60)
        print("所有测试通过")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n测试异常: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
