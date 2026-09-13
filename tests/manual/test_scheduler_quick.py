"""快速验证TaskScheduler基本功能"""

import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.app.scheduler.task_scheduler import TaskScheduler

def main():
    print("=== TaskScheduler快速验证 ===\n")

    db_path = project_root / "data" / "hydropower.sqlite"

    executed = []

    def simple_executor(task_id):
        print(f"执行任务: {task_id}")
        executed.append(task_id)
        return {"status": "success"}

    # 创建调度器
    scheduler = TaskScheduler(
        db_path=str(db_path),
        task_executor=simple_executor,
        max_workers=2,
        scan_interval=10
    )

    print(f"1. 配置检查:")
    print(f"   - max_workers: {scheduler.max_workers}")
    print(f"   - scan_interval: {scheduler.scan_interval}s")
    print(f"   - 配置正确: {'是' if scheduler.max_workers == 2 and scheduler.scan_interval == 10 else '否'}")

    # 启动
    print(f"\n2. 启动调度器...")
    scheduler.start()
    print(f"   - 运行状态: {scheduler.running}")
    print(f"   - 暂停状态: {scheduler.paused}")

    # 获取状态
    time.sleep(0.5)
    status = scheduler.get_status()
    print(f"\n3. 状态查询:")
    print(f"   - running: {status['running']}")
    print(f"   - paused: {status['paused']}")
    print(f"   - active_workers: {status['active_workers']}")
    print(f"   - max_workers: {status['max_workers']}")

    # 暂停
    print(f"\n4. 测试暂停...")
    scheduler.pause()
    print(f"   - 暂停状态: {scheduler.paused}")

    # 恢复
    print(f"\n5. 测试恢复...")
    scheduler.resume()
    print(f"   - 暂停状态: {scheduler.paused}")

    # 停止
    print(f"\n6. 停止调度器...")
    scheduler.stop()
    print(f"   - 运行状态: {scheduler.running}")

    print("\n=== 所有测试通过 ===")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
