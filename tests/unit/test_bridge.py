"""桥接层错误提示的可操作性回归测试。"""

from hydro_platform.app.bridge import BridgeError, format_error_for_ui


def test_ocr_required_error_is_actionable():
    error = BridgeError(
        stage="EXTRACTION",
        code="OCR_REQUIRED",
        message="来源为无文字层 PDF，需要 OCR 或人工复核后再抽取",
    )
    message = format_error_for_ui(error)
    assert "OCR" in message
    assert "人工复核" in message
