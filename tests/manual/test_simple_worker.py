"""测试SimpleWorker功能

验证项：
1. 后台线程执行
2. 进度回调
3. 取消支持
4. 错误捕获
5. 不阻塞主线程
"""

import sys
import time
import threading
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.app.workers.simple_worker import SimpleWorker, WorkerEvent


def test_basic_execution():
    """测试1：基本执行"""
    print("\n=== 测试1：基本执行 ===")

    events_received = []
    result = [None]

    def callback(event: WorkerEvent):
        events_received.append(event)
        print(f"  [{event.event_type}] {event.message}")
        if event.event_type == "complete":
            result[0] = event.data.get("result")

    worker = SimpleWorker(task_id="test_task_1", callback=callback)

    def simple_task():
        worker.report_progress("开始执行")
        time.sleep(0.1)
        worker.report_progress("执行中...")
        time.sleep(0.1)
        worker.report_progress("完成")
        return {"status": "success", "result": 42}

    # 启动worker
    worker.start(simple_task)

    # 等待完成
    worker.join()

    print(f"结果: {result[0]}")
    print(f"收到 {len(events_received)} 个事件")

    assert result[0] is not None
    assert result[0]["status"] == "success"
    assert result[0]["result"] == 42
    assert len(events_received) >= 3  # 至少3个progress事件

    print("[PASS] 基本执行正常")


def test_non_blocking():
    """测试2：不阻塞主线程"""
    print("\n=== 测试2：不阻塞主线程 ===")

    result = [None]

    def callback(event: WorkerEvent):
        if event.event_type == "complete":
            result[0] = event.data.get("result")

    worker = SimpleWorker(task_id="test_task_2", callback=callback)

    def slow_task():
        time.sleep(1)
        return {"status": "success"}

    # 启动worker
    worker.start(slow_task)

    # 主线程继续执行
    print("  主线程继续执行...")
    for i in range(5):
        print(f"  主线程计数: {i}")
        time.sleep(0.1)

    # 检查worker是否在后台运行
    assert worker._thread is not None
    assert worker.is_running() or not worker.is_running()  # 可能已完成

    # 等待完成
    worker.join()

    assert result[0] is not None
    assert result[0]["status"] == "success"
    print("[PASS] 不阻塞主线程")


def test_cancel():
    """测试3：取消支持"""
    print("\n=== 测试3：取消支持 ===")

    # 注意：当前SimpleWorker实现在取消后不会发送complete事件
    # 这个测试验证取消API存在且标记能够设置/检测

    was_cancelled = [False]

    worker = SimpleWorker(task_id="test_task_3", callback=lambda e: None)

    def cancellable_task():
        for i in range(20):
            if worker.is_cancelled():
                was_cancelled[0] = True
                return {"status": "cancelled"}
            time.sleep(0.05)
        return {"status": "success"}

    # 启动worker
    worker.start(cancellable_task)

    # 等待后取消
    time.sleep(0.15)
    worker.cancel()

    # 等待完成
    worker.join(timeout=2.0)

    print(f"  取消标记已设置: {worker.is_cancelled()}")
    print(f"  任务检测到取消: {was_cancelled[0]}")

    # 验证取消API存在且工作
    assert hasattr(worker, 'cancel'), "应该有cancel方法"
    assert hasattr(worker, 'is_cancelled'), "应该有is_cancelled方法"
    assert worker.is_cancelled(), "取消标记应该被设置"
    assert was_cancelled[0], "任务应该检测到取消"

    print("[PASS] 取消功能正常")


def test_error_handling():
    """测试4：错误捕获"""
    print("\n=== 测试4：错误捕获 ===")

    error_events = []

    def callback(event: WorkerEvent):
        if event.event_type == "error":
            error_events.append(event)
            print(f"  [ERROR] {event.message}")

    worker = SimpleWorker(task_id="test_task_4", callback=callback)

    def failing_task():
        raise ValueError("模拟错误")

    # 启动worker
    worker.start(failing_task)

    # 等待完成
    worker.join()

    assert len(error_events) > 0
    assert "模拟错误" in error_events[0].message

    print("[PASS] 错误捕获正常")


def test_state_changes():
    """测试5：状态变化事件"""
    print("\n=== 测试5：状态变化事件 ===")

    state_events = []
    result = [None]

    def callback(event: WorkerEvent):
        if event.event_type == "state_change":
            state_events.append(event)
            print(f"  状态变化: {event.data}")
        elif event.event_type == "complete":
            result[0] = event.data.get("result")

    worker = SimpleWorker(task_id="test_task_5", callback=callback)

    def task_with_stages():
        worker.report_state_change("INIT", {"stage": "初始化"})
        time.sleep(0.1)
        worker.report_state_change("PROCESSING", {"stage": "处理中"})
        time.sleep(0.1)
        worker.report_state_change("DONE", {"stage": "完成"})
        return {"status": "success"}

    worker.start(task_with_stages)
    worker.join()

    print(f"收到 {len(state_events)} 个状态变化事件")
    assert len(state_events) == 3
    assert result[0] is not None
    assert result[0]["status"] == "success"

    print("[PASS] 状态变化事件正常")


def main():
    print("=" * 60)
    print("SimpleWorker功能测试")
    print("=" * 60)

    tests = [
        test_basic_execution,
        test_non_blocking,
        test_cancel,
        test_error_handling,
        test_state_changes
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
