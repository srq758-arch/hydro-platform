"""采集入口必须收口到可信 Pipeline 的回归测试。"""

import inspect

from hydro_platform.app.api import Api
import hydro_platform.app.gui.main_window as main_window
from hydro_platform.app.gui.main_window import HydroPlatformApp
from hydro_platform.common.enums import ContentKind, EntityType, TaskStatus, TaskType
from hydro_platform.models.task import Task
from hydro_platform.tasking.manager import TaskManager


def test_run_collection_task_defaults_to_content_auto_detection():
    default = inspect.signature(Api.run_collection_task).parameters["expected"].default
    assert default is ContentKind.ANY
    assert not hasattr(Api, "download_and_archive")
    assert not hasattr(Api, "archive_local_file")
    assert not hasattr(Api, "parse_file")
    assert not hasattr(Api, "extract_file")
    assert not hasattr(Api, "save_candidates_to_database")


def test_legacy_content_kind_fallback_is_content_agnostic():
    api = Api("test")
    assert api._legacy_guess_content_kind("unknown-extension.bin") is ContentKind.ANY


def test_desktop_start_task_rejects_legacy_context_free_request():
    result = HydroPlatformApp().start_task(
        {"type": "download_url", "url": "https://example.test/source"}
    )

    assert result == {
        "status": "failed",
        "error_stage": "VALIDATION",
        "error_code": "MISSING_BUSINESS_CONTEXT",
        "error_message": "采集任务必须指定目标电站和目标年份；旧桌面流程已停用。",
    }


def test_desktop_start_task_forwards_new_source_title(monkeypatch):
    captured = {}

    class FakeApi:
        def run_collection_task(self, **kwargs):
            captured.update(kwargs)
            return {
                "status": "failed",
                "task_id": "task-test",
                "final_status": "failed",
                "documents_archived": 0,
                "candidates_extracted": 0,
                "candidates_promoted": 0,
                "error": "test failure",
            }

    class FakeWorker:
        def __init__(self, task_id, callback):
            self.task_id = task_id
            self.callback = callback

        def report_state_change(self, *args, **kwargs):
            pass

        def report_progress(self, *args, **kwargs):
            pass

        def is_cancelled(self):
            return False

        def start(self, callback):
            callback()

    app = HydroPlatformApp()
    monkeypatch.setattr(main_window, "SimpleWorker", FakeWorker)
    monkeypatch.setattr(app, "_get_api", lambda data_mode="production": FakeApi())

    result = app.start_task({
        "type": "download_url",
        "entity_id": "station-test",
        "target_period": "2024",
        "url": "https://example.test/report",
        "source_title": "官方 2024 年报",
        "data_mode": "test",
    })

    assert result["status"] == "started"
    assert captured["source_title"] == "官方 2024 年报"


def test_explicit_source_can_reopen_cancelled_task(db):
    task = Task(
        task_id="station_reopen::station_generation::2024",
        entity_id="station_reopen",
        entity_type=EntityType.STATION,
        task_type=TaskType.STATION_GENERATION,
        target_period="2024",
    )
    manager = TaskManager(db)
    manager.repo.upsert_many([task])
    manager.cancel(task.task_id)

    assert manager.reopen_cancelled_for_explicit_source(task.task_id) is True
    row = manager.repo.get(task.task_id)
    assert row["status"] == TaskStatus.PENDING.value
    assert row["failure_stage"] is None
    assert row["last_error"] is None
