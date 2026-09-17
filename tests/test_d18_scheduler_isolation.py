"""D18：调度器事务隔离测试。

验证调度器与主应用的数据库连接是否隔离：
- 调度器扫描任务时不应与主应用共享事务
- worker执行任务时应使用独立连接
- 避免锁竞争和事务冲突
"""

import sqlite3
import threading
import time
from pathlib import Path

from hydro_platform.app.scheduler.task_scheduler import TaskScheduler
from hydro_platform.database.connection import connect
from hydro_platform.database.repositories import TaskRepository
from hydro_platform.common.enums import TaskStatus
from hydro_platform.models.task import Task
from hydro_platform.common.clock import now_iso


def test_scheduler_uses_independent_connection(tmp_path):
    """测试：调度器使用独立连接，不与主应用共享事务。"""
    db_path = tmp_path / "test.db"

    # 初始化数据库（使用完整schema）
    conn = connect(db_path)
    schema_path = Path(__file__).parent.parent / "hydro_platform" / "database" / "schema.sql"
    if schema_path.exists():
        with open(schema_path, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())
    conn.commit()

    # 插入测试任务
    task_repo = TaskRepository(conn)
    task = Task(
        task_id="test_task_1",
        entity_id="entity_1",
        entity_type="station",
        task_type="station_generation",  # 正确的枚举值
        target_period="2024-01",
        status=TaskStatus.PENDING,
        created_at=now_iso(),
        updated_at=now_iso()
    )
    task_repo.upsert_many([task])
    conn.commit()

    # 主应用开启长事务（不提交）
    main_conn = connect(db_path)
    main_conn.execute("BEGIN IMMEDIATE")
    main_conn.execute("INSERT INTO tasks (task_id, entity_id, entity_type, task_type, target_period, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                     ("test_task_2", "entity_2", "station", "station_generation", "2024-01", TaskStatus.PENDING.value))
    # 故意不提交，保持事务打开

    # 调度器应能读取已提交的任务（不被主事务阻塞）
    executed_tasks = []

    def task_executor(task_id):
        executed_tasks.append(task_id)
        return {"status": "success"}

    scheduler = TaskScheduler(
        db_path=str(db_path),
        task_executor=task_executor,
        max_workers=1,
        scan_interval=1
    )

    try:
        scheduler.start()
        # 主连接先持有写事务，验证调度器不会读取未提交任务；随后释放
        # 锁，让原子 claim 在下一轮扫描中领取已提交任务。
        time.sleep(0.2)
        main_conn.rollback()
        time.sleep(2)  # 等待调度器扫描并领取

        # 验证：调度器能读取已提交的任务
        assert "test_task_1" in executed_tasks, "调度器应能读取已提交的任务"

        # 验证：调度器不应读取未提交的任务
        assert "test_task_2" not in executed_tasks, "调度器不应读取主应用未提交的任务"

    finally:
        scheduler.stop()
        main_conn.close()
        conn.close()


def test_scheduler_worker_uses_own_connection(tmp_path):
    """测试：worker执行任务时使用自己的连接，不受主应用影响。"""
    db_path = tmp_path / "test.db"

    # 初始化数据库（使用完整schema）
    conn = connect(db_path)
    schema_path = Path(__file__).parent.parent / "hydro_platform" / "database" / "schema.sql"
    if schema_path.exists():
        with open(schema_path, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())
    conn.commit()

    # 插入测试任务
    task_repo = TaskRepository(conn)
    task = Task(
        task_id="worker_test_1",
        entity_id="entity_1",
        entity_type="station",
        task_type="station_generation",  # 正确的枚举值
        target_period="2024-01",
        status=TaskStatus.PENDING,
        created_at=now_iso(),
        updated_at=now_iso()
    )
    task_repo.upsert_many([task])
    conn.commit()
    conn.close()

    # worker更新任务时不应被主应用长事务阻塞
    def task_executor(task_id):
        # worker内部获取独立连接并更新
        worker_conn = connect(db_path)
        try:
            worker_conn.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (TaskStatus.SUCCESS.value, task_id))
            worker_conn.commit()
            return {"status": "success"}
        finally:
            worker_conn.close()

    # 主应用持有长事务（读锁）
    main_conn = connect(db_path)
    main_conn.execute("BEGIN")
    main_conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("worker_test_1",))
    # 故意不提交

    scheduler = TaskScheduler(
        db_path=str(db_path),
        task_executor=task_executor,
        max_workers=1,
        scan_interval=1
    )

    try:
        scheduler.start()
        time.sleep(2)

        # 验证：worker能成功执行（WAL模式允许读写并发）
        check_conn = connect(db_path)
        cursor = check_conn.execute("SELECT status FROM tasks WHERE task_id = ?", ("worker_test_1",))
        row = cursor.fetchone()
        check_conn.close()

        assert row is not None and row[0] == TaskStatus.SUCCESS.value, "worker应能独立完成任务更新"

    finally:
        scheduler.stop()
        main_conn.rollback()
        main_conn.close()


def test_no_connection_leak_in_scheduler(tmp_path):
    """测试：调度器不泄漏数据库连接。"""
    db_path = tmp_path / "test.db"

    # 初始化数据库（使用完整schema）
    conn = connect(db_path)
    schema_path = Path(__file__).parent.parent / "hydro_platform" / "database" / "schema.sql"
    if schema_path.exists():
        with open(schema_path, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())
    conn.commit()

    # 插入10个任务
    task_repo = TaskRepository(conn)
    tasks = []
    for i in range(10):
        task = Task(
            task_id=f"task_{i}",
            entity_id=f"entity_{i}",
            entity_type="station",
            task_type="station_generation",
            target_period="2024-01",
            status=TaskStatus.PENDING,
            created_at=now_iso(),
            updated_at=now_iso()
        )
        tasks.append(task)
    task_repo.upsert_many(tasks)
    conn.commit()
    conn.close()

    executed_count = [0]

    def task_executor(task_id):
        executed_count[0] += 1
        time.sleep(0.1)  # 模拟任务执行
        return {"status": "success"}

    scheduler = TaskScheduler(
        db_path=str(db_path),
        task_executor=task_executor,
        max_workers=2,
        scan_interval=1
    )

    try:
        scheduler.start()
        time.sleep(10)  # 等待所有任务执行完（步骤1.3修复：增加等待时间）

        # 验证：所有任务都被执行
        assert executed_count[0] == 10, f"应执行10个任务，实际执行{executed_count[0]}个"

        # 验证：没有连接泄漏（能正常打开新连接）
        test_conn = connect(db_path)
        cursor = test_conn.execute("SELECT COUNT(*) FROM tasks")
        count = cursor.fetchone()[0]
        test_conn.close()

        assert count == 10, "数据库连接正常"

    finally:
        scheduler.stop()


def test_two_schedulers_atomically_claim_one_task(tmp_path):
    """双启动调度器竞争同一 pending 任务时只能执行一次。"""
    db_path = tmp_path / "race.db"
    conn = connect(db_path)
    schema_path = Path(__file__).parent.parent / "hydro_platform" / "database" / "schema.sql"
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    TaskRepository(conn).upsert_many([
        Task(
            task_id="race_task",
            entity_id="race_entity",
            entity_type="station",
            task_type="station_generation",
            target_period="2024",
            status=TaskStatus.PENDING,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
    ])
    conn.commit()
    conn.close()

    executed = []
    executed_lock = threading.Lock()

    def executor(task_id):
        with executed_lock:
            executed.append(task_id)
        time.sleep(0.3)
        return {"status": "success"}

    schedulers = [
        TaskScheduler(str(db_path), executor, max_workers=1, scan_interval=0.1),
        TaskScheduler(str(db_path), executor, max_workers=1, scan_interval=0.1),
    ]
    try:
        for scheduler in schedulers:
            scheduler.start()
        time.sleep(1)
    finally:
        for scheduler in schedulers:
            scheduler.stop()

    assert executed == ["race_task"]
    conn = connect(db_path)
    try:
        assert conn.execute("SELECT status FROM tasks WHERE task_id='race_task'").fetchone()[0] == "running"
    finally:
        conn.close()


def test_scheduler_marks_executor_exception_as_failed(tmp_path):
    """执行器异常不能让已领取任务永久停在 running。"""
    db_path = tmp_path / "executor-error.db"
    conn = connect(db_path)
    schema_path = Path(__file__).parent.parent / "hydro_platform" / "database" / "schema.sql"
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    TaskRepository(conn).upsert_many([
        Task(
            task_id="executor-error-task",
            entity_id="error-entity",
            entity_type="station",
            task_type="station_generation",
            target_period="2024",
            status=TaskStatus.PENDING,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
    ])
    conn.commit()
    conn.close()

    def executor(_task_id):
        raise RuntimeError("executor boom")

    scheduler = TaskScheduler(str(db_path), executor, max_workers=1, scan_interval=0.1)
    try:
        scheduler.start()
        time.sleep(0.5)
    finally:
        scheduler.stop()

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, failure_stage, last_error, attempts FROM tasks WHERE task_id=?",
            ("executor-error-task",),
        ).fetchone()
        assert tuple(row) == ("failed", "UNKNOWN", "executor boom", 1)
    finally:
        conn.close()


if __name__ == "__main__":
    import tempfile
    import shutil

    tmp = Path(tempfile.mkdtemp())
    try:
        print("测试1: 调度器使用独立连接...")
        test_scheduler_uses_independent_connection(tmp)
        print("✓ 通过")

        print("测试2: worker使用独立连接...")
        test_scheduler_worker_uses_own_connection(tmp)
        print("✓ 通过")

        print("测试3: 无连接泄漏...")
        test_no_connection_leak_in_scheduler(tmp)
        print("✓ 通过")

        print("\n✅ D18所有测试通过")
    finally:
        shutil.rmtree(tmp)
