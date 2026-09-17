"""前端导航状态：页面重绘后不能丢失草稿或动态结果。"""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_navigation_state_harness_preserves_user_drafts_and_safe_exclusions():
    result = subprocess.run(
        [
            "node",
            str(ROOT / "tests" / "unit" / "frontend_navigation_state_harness.js"),
            str(ROOT / "hydro_platform" / "app" / "web" / "app.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "passed" in result.stdout


def test_add_data_uses_the_defined_history_writer():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "function addToHistory(record)" in source
    assert "addProcessHistory(" not in source


def test_review_actions_quote_string_review_ids():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "const reviewIdLiteral = JSON.stringify(reviewId);" in source
    assert "data-review-id=" in source
    assert "const id = cb.dataset.reviewId;" in source


def test_review_actions_do_not_treat_structured_api_failures_as_success():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "function ensureReviewActionSuccess(result)" in source
    assert source.count("ensureReviewActionSuccess(result);") >= 6
    assert "result?.message || '复核操作失败'" in source


def test_legacy_batch_file_path_keeps_business_context_and_fails_fast():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "const entityId = el('input-station-id')?.value.trim();" in source
    assert "const targetPeriod = el('input-target-year')?.value.trim();" in source
    assert "批量处理必须指定目标电站和目标年份" in source
    assert "target_period: targetPeriod" in source
    assert "startResult?.error_message || '任务启动失败'" in source


def test_legacy_batch_events_restore_global_handler_and_accept_review_completion():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    # 批量入口只能临时接管事件；否则下一次页面任务会继续落入已结束的闭包。
    assert "const previousHandler = window.onTaskEvent;" in source
    assert "window.onTaskEvent = previousHandler;" in source
    assert "if (expectedTaskId && event.task_id && event.task_id !== expectedTaskId)" in source
    # needs_review 是有效的 Pipeline 完成态，不能在批量流程中被误判为失败。
    assert "result?.status === 'success' || result?.status === 'needs_review'" in source


def test_guide_route_and_first_use_onboarding_are_available():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "guide: renderGuide" in source
    assert "function showFirstUseGuide(force = false)" in source
    assert "navigate('dashboard').then(() => setTimeout(() => showFirstUseGuide(), 0));" in source


def test_station_details_use_unified_trusted_source_discovery_not_gem_only_lookup():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "onclick=\"discoverTrustedSources(" in source
    assert "api().discover_trusted_sources(entityId, year, 10, periodType)" in source
    assert "function discoverOfficialSources(" not in source


def test_discovery_dialog_separates_qualified_review_and_excluded_items():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "const excludedItems = result.excluded_items || [];" in source
    assert "const excludedRows = excludedItems.map(item =>" in source
    assert "excludedItems.length" in source
    assert "canOpen ?" in source


def test_discovery_dialog_explains_provider_budget_and_cost_diagnostics():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "速率受限" in source
    assert "预算耗尽" in source
    assert "已熔断" in source
    assert "估算成本" in source
