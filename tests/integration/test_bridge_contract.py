"""GUI Bridge 与前端调用契约测试。"""

from __future__ import annotations

import re
from pathlib import Path

from hydro_platform.app.gui.main_window import HydroPlatformApp
from hydro_platform.config.paths import get_database_path
from hydro_platform.app.cli.commands import get_db_path


def _frontend_calls() -> set[str]:
    root = Path(__file__).parents[2] / "hydro_platform" / "app"
    text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in {".html", ".js"}
    )
    return set(re.findall(r"pywebview\.api\.([A-Za-z_]\w*)", text))


def _frontend_api_calls() -> set[str]:
    root = Path(__file__).parents[2] / "hydro_platform" / "app"
    text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in {".html", ".js"}
    )
    return set(re.findall(r"api\(\)\.([A-Za-z_]\w*)", text))


def _bridge_methods() -> set[str]:
    return {
        name
        for name in dir(HydroPlatformApp)
        if not name.startswith("_") and callable(getattr(HydroPlatformApp, name))
    }


def test_every_frontend_api_call_is_exposed_by_bridge():
    missing = sorted((_frontend_calls() | _frontend_api_calls()) - _bridge_methods())
    assert missing == [], f"前端调用未暴露到 Bridge: {missing}"


def test_bridge_missing_gui_window_returns_structured_error():
    result = HydroPlatformApp().open_review_window("review-1")
    assert result["status"] == "failed"
    assert result["review_id"] == "review-1"
    assert result["message"]


def test_cli_and_api_use_the_same_default_database_space(monkeypatch, tmp_path):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path))
    assert get_db_path(None) == get_database_path("production")
    assert get_db_path(None).name == "hydro.db"
