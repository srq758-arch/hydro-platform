"""旧 CLI 入口重建任务时必须保留完整任务语义。"""

from hydro_platform.app.cli.commands import _task_from_row


def test_cli_task_mapping_preserves_period_and_manual_source():
    task = _task_from_row({
        "task_id": "station::station_generation::2024::fiscal_year",
        "entity_id": "station",
        "entity_type": "station",
        "task_type": "station_generation",
        "target_period": "2024",
        "period_type": "fiscal_year",
        "status": "pending",
        "source_type": "manual",
        "user_specified_source": "https://operator.example/report.html",
        "attempts": 0,
        "max_attempts": 3,
    })

    assert task.period_type.value == "fiscal_year"
    assert task.source_type == "manual"
    assert task.user_specified_source == "https://operator.example/report.html"


def test_cli_task_mapping_defaults_fields_for_legacy_row():
    task = _task_from_row({
        "task_id": "station::station_generation::2024",
        "entity_id": "station",
        "entity_type": "station",
        "task_type": "station_generation",
        "target_period": "2024",
        "status": "pending",
    })

    assert task.period_type.value == "calendar_year"
    assert task.source_type == "automatic"
    assert task.user_specified_source is None
