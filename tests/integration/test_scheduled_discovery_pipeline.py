"""调度任务必须把自动发现和浏览器回退正确交给可信 Pipeline。"""

from unittest.mock import patch

from hydro_platform.app.api import Api
from hydro_platform.common.enums import TaskStatus
from hydro_platform.intelligence.source_discovery_service import TaskSourceDiscoveryAdapter
from hydro_platform.pipeline.result import PipelineResult


def test_scheduled_task_builds_automatic_discovery_context(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("test")
    api.initialize()
    conn = api.get_db_connection()
    conn.execute(
        """INSERT INTO stations (entity_id, canonical_name, country, gem_wiki_url)
           VALUES ('station_scheduled', 'Scheduled Dam', 'Exampleland', 'https://www.gem.wiki/Scheduled_Dam')"""
    )
    conn.execute(
        """INSERT INTO tasks (task_id, entity_id, entity_type, task_type, target_period, status, created_at, updated_at)
           VALUES ('scheduled_task', 'station_scheduled', 'station', 'station_generation', '2024', 'pending', datetime('now'), datetime('now'))"""
    )
    conn.commit()
    conn.close()

    observed = {}

    def fake_run(ctx, task):
        observed["task_id"] = task.task_id
        observed["resolver"] = ctx.discovery_resolver
        observed["controlled_refs"] = ctx.url_resolver.resolve(task)
        return PipelineResult(task_id=task.task_id, final_status=TaskStatus.SUCCESS, reached_stage="done")

    with patch("hydro_platform.app.api.Api._build_acquisition_router") as build_router, \
         patch("hydro_platform.pipeline.orchestrator.run_task", side_effect=fake_run):
        result = api.execute_scheduled_task("scheduled_task")

    assert result["status"] == "success"
    assert result["task_id"] == "scheduled_task"
    assert observed["task_id"] == "scheduled_task"
    assert isinstance(observed["resolver"], TaskSourceDiscoveryAdapter)
    assert observed["controlled_refs"] == []
    assert build_router.called
