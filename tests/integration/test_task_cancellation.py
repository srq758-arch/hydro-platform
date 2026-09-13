"""取消在采集边界发生时不得继续归档或发布。"""

from pathlib import Path

from hydro_platform.acquisition.result import DownloadMeta, FetchResult
from hydro_platform.common.enums import AccessMethod, ContentKind, EntityType, TaskType
from hydro_platform.models.task import Task
from hydro_platform.pipeline import PipelineContext, SourceRef
from hydro_platform.pipeline.orchestrator import run_task
from hydro_platform.tasking.manager import TaskManager


class _CancellingRouter:
    def __init__(self, conn):
        self.conn = conn

    def fetch(self, url, *, expected):
        self.conn.execute("UPDATE tasks SET status='cancelled' WHERE task_id=?", (self.task_id,))
        self.conn.commit()
        return FetchResult(
            success=True,
            meta=DownloadMeta(
                original_url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                file_size=12,
                content_hash="cancelled-hash",
                content_kind=ContentKind.HTML,
                access_method=AccessMethod.HTTP,
                fetched_at="2026-01-01T00:00:00Z",
            ),
            body=b"2024 generation 1 GWh",
        )


class _Resolver:
    def resolve(self, _task):
        return [SourceRef("https://example.test/cancel", ContentKind.HTML)]


def test_cancellation_stops_before_archive(db, tmp_path):
    task = Task(
        task_id="station_cancel::station_generation::2024",
        entity_id="station_cancel",
        entity_type=EntityType.STATION,
        task_type=TaskType.STATION_GENERATION,
        target_period="2024",
    )
    TaskManager(db).repo.upsert_many([task])
    router = _CancellingRouter(db)
    router.task_id = task.task_id
    ctx = PipelineContext(
        conn=db,
        router=router,
        url_resolver=_Resolver(),
        raw_root=Path(tmp_path) / "raw",
    )

    result = run_task(ctx, task)

    assert result.final_status.value == "cancelled"
    assert result.documents_archived == 0
    assert db.execute("SELECT status FROM tasks WHERE task_id=?", (task.task_id,)).fetchone()[0] == "cancelled"
    run = db.execute("SELECT status, failure_stage FROM task_runs WHERE task_id=?", (task.task_id,)).fetchone()
    assert run["status"] == "failed"
    assert run["failure_stage"] == "CANCELLED"
