"""任务列表操作 API：取消、失败重试和测试任务批量取消。"""

from hydro_platform.app.api import Api
from hydro_platform.common.enums import EntityType, FailureStage, TaskType
from hydro_platform.models.task import Task
from hydro_platform.tasking.manager import TaskManager


def _api_with_tasks(monkeypatch, tmp_path):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path))
    api = Api(data_mode="test")
    api.initialize()
    return api


def _insert_task(api, task_id, entity_id):
    conn = api.get_db_connection()
    task = Task(
        task_id=task_id,
        entity_id=entity_id,
        entity_type=EntityType.STATION,
        task_type=TaskType.STATION_GENERATION,
        target_period="2024",
    )
    TaskManager(conn).repo.upsert_many([task])
    conn.commit()
    conn.close()


def test_cancel_queued_task_preserves_row_and_sets_cancelled(monkeypatch, tmp_path):
    api = _api_with_tasks(monkeypatch, tmp_path)
    task_id = "test_station::station_generation::2024"
    _insert_task(api, task_id, "test_station")

    assert api.cancel_queued_task(task_id) == {
        "success": True, "task_id": task_id, "status": "cancelled"
    }
    conn = api.get_db_connection()
    assert conn.execute("SELECT status FROM tasks WHERE task_id = ?", (task_id,)).fetchone()[0] == "cancelled"
    conn.close()


def test_retry_failed_task_requeues_when_under_retry_limit(monkeypatch, tmp_path):
    api = _api_with_tasks(monkeypatch, tmp_path)
    task_id = "retry_station::station_generation::2024"
    _insert_task(api, task_id, "retry_station")
    conn = api.get_db_connection()
    manager = TaskManager(conn)
    manager.claim(task_id)
    manager.mark_failed(task_id, failure_stage=FailureStage.PARSE_FAILED)
    conn.close()

    assert api.retry_failed_task(task_id) == {
        "success": True, "task_id": task_id, "status": "pending"
    }


def test_cancel_test_tasks_only_cancels_nonterminal_test_prefix_tasks(monkeypatch, tmp_path):
    api = _api_with_tasks(monkeypatch, tmp_path)
    _insert_task(api, "test_pending::station_generation::2024", "test_pending")
    _insert_task(api, "test_done::station_generation::2024", "test_done")
    _insert_task(api, "real_pending::station_generation::2024", "real_pending")
    conn = api.get_db_connection()
    manager = TaskManager(conn)
    manager.claim("test_done::station_generation::2024")
    manager.mark_success("test_done::station_generation::2024")
    conn.close()

    result = api.cancel_test_tasks()
    assert result["success"] is True
    assert result["cancelled_count"] == 1
    assert result["skipped_count"] == 1
    conn = api.get_db_connection()
    statuses = dict(conn.execute("SELECT task_id, status FROM tasks").fetchall())
    assert statuses["test_pending::station_generation::2024"] == "cancelled"
    assert statuses["test_done::station_generation::2024"] == "success"
    assert statuses["real_pending::station_generation::2024"] == "pending"
    conn.close()


def test_create_task_preserves_requested_task_type_and_rejects_unknown(monkeypatch, tmp_path):
    api = _api_with_tasks(monkeypatch, tmp_path)

    capacity = api.create_task(
        "station_capacity_target", "-", task_type="station_capacity"
    )
    assert capacity["success"] is True
    assert capacity["task_id"] == "station_capacity_target::station_capacity::-"

    project = api.create_task(
        "project_target", "2026", task_type="project_status"
    )
    assert project["success"] is True
    conn = api.get_db_connection()
    row = conn.execute(
        "SELECT entity_type, task_type FROM tasks WHERE task_id = ?",
        (project["task_id"],),
    ).fetchone()
    conn.close()
    assert tuple(row) == ("project", "project_status")

    invalid = api.create_task("station_invalid", "2024", task_type="typo_metric")
    assert invalid == {"success": False, "error": "不支持的任务类型: typo_metric"}
