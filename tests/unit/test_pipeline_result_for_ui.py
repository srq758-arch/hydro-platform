"""桌面端 Pipeline 事件结果的回归测试。"""

from hydro_platform.app.gui.main_window import _pipeline_result_for_ui


def _result(**overrides):
    result = {
        "status": "failed",
        "task_id": "task-1",
        "final_status": "FAILED",
        "documents_archived": 0,
        "candidates_extracted": 0,
        "candidates_promoted": 0,
        "review_ids": [],
        "promoted_keys": [],
        "failure_stage": "ACQUISITION_FAILED",
        "error": "响应内容是 HTML，不是 PDF",
    }
    result.update(overrides)
    return result


def test_pipeline_failure_uses_legacy_and_current_error_fields():
    """前端旧、新字段都必须能得到真实失败原因，不能回落为 UNKNOWN。"""
    payload = _pipeline_result_for_ui(_result())

    assert payload["failure_stage"] == "ACQUISITION_FAILED"
    assert payload["error"] == "响应内容是 HTML，不是 PDF"
    assert payload["error_stage"] == "ACQUISITION_FAILED"
    assert payload["error_code"] == "PIPELINE_FAILED"
    assert payload["error_message"] == "响应内容是 HTML，不是 PDF"


def test_pipeline_success_does_not_invent_error_fields():
    payload = _pipeline_result_for_ui(
        _result(status="success", final_status="COMPLETED", failure_stage=None, error=None)
    )

    assert payload["error_stage"] is None
    assert payload["error_code"] is None
    assert payload["error_message"] is None
