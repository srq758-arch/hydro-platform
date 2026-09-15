"""三个独立原子任务共享 SQLite 数据库的真实并发回归。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hydro_platform.acquisition.http_client import HttpClient
from hydro_platform.acquisition.router import AcquisitionRouter
from hydro_platform.acquisition.transport import RawResponse
from hydro_platform.common.enums import ContentKind, EntityType, TaskStatus, TaskType
from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import migrate
from hydro_platform.database.repositories import TaskRepository
from hydro_platform.models.task import Task
from hydro_platform.pipeline import PipelineContext, SourceRef
from hydro_platform.pipeline.orchestrator import run_task


FIXTURE = Path(__file__).parent.parent / "fixtures" / "three_gorges_2020.html"


class _Resolver:
    def __init__(self, url: str):
        self.url = url

    def resolve(self, task):
        return [SourceRef(url=self.url, expected=ContentKind.HTML, title="Three Gorges 2020")]


class _ReplayTransport:
    def __init__(self, url: str, body: bytes):
        self.url = url
        self.body = body

    def fetch(self, url: str, *, headers, timeout):
        if url != self.url:
            raise AssertionError(f"unexpected URL: {url}")
        return RawResponse(
            status_code=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=self.body,
            final_url=url,
        )


def test_three_parallel_atomic_tasks_complete_without_database_locked(tmp_path):
    """真实执行三个完整闭环；网络边界回放，其他均为生产实现。"""
    db_path = tmp_path / "parallel-pipeline.db"
    raw_root = tmp_path / "raw"
    setup = connect(db_path, timeout=10.0)
    migrate(setup)
    tasks: list[Task] = []
    for index in range(3):
        entity_id = f"parallel-station-{index}"
        setup.execute(
            """INSERT INTO stations(
                   entity_id, entity_type, canonical_name, capacity_mw, priority_tier
               ) VALUES (?, 'station', 'Three Gorges Dam', 22500, 'C')""",
            (entity_id,),
        )
        tasks.append(
            Task(
                task_id=Task.derive_id(entity_id, TaskType.STATION_GENERATION, "2020"),
                entity_id=entity_id,
                entity_type=EntityType.STATION,
                task_type=TaskType.STATION_GENERATION,
                target_period="2020",
            )
        )
    TaskRepository(setup).upsert_many(tasks)
    setup.commit()
    setup.close()

    def execute(task: Task):
        url = f"https://parallel.example.test/{task.entity_id}/2020"
        conn = connect(db_path, timeout=10.0)
        try:
            ctx = PipelineContext(
                conn=conn,
                router=AcquisitionRouter(
                    http_client=HttpClient(
                        transport=_ReplayTransport(url, FIXTURE.read_bytes())
                    )
                ),
                url_resolver=_Resolver(url),
                raw_root=raw_root,
            )
            return run_task(ctx, task)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(execute, tasks))

    assert all(
        result.final_status in (TaskStatus.SUCCESS, TaskStatus.NEEDS_REVIEW)
        for result in results
    )
    check = connect(db_path, read_only=True)
    try:
        statuses = check.execute(
            "SELECT status FROM tasks ORDER BY task_id"
        ).fetchall()
        assert {row[0] for row in statuses}.issubset({"success", "needs_review"})
        assert check.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        check.close()
