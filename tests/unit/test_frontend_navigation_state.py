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


def test_guide_route_and_first_use_onboarding_are_available():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "guide: renderGuide" in source
    assert "function showFirstUseGuide(force = false)" in source
    assert "navigate('dashboard').then(() => setTimeout(() => showFirstUseGuide(), 0));" in source


def test_station_details_use_unified_trusted_source_discovery_not_gem_only_lookup():
    source = (ROOT / "hydro_platform" / "app" / "web" / "app.js").read_text(encoding="utf-8")

    assert "onclick=\"discoverTrustedSources(" in source
    assert "api().discover_trusted_sources(entityId, year, 10)" in source
    assert "function discoverOfficialSources(" not in source
