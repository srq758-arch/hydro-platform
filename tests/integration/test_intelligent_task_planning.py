"""自然语言智能任务：规划、URL 预检、候选确认和正式任务必须严格分离。"""

from unittest.mock import patch

from hydro_platform.app.api import Api
from hydro_platform.intelligence.deepseek_agent import TaskIntent


def _reachable(values):
    return [{
        **item, "access_status": "reachable", "status": "discovered", "http_status": 200,
        "final_url": item["url"], "error": None,
    } for item in values]


def test_intelligent_task_creates_plan_then_requires_candidate_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("test")
    api.initialize()
    conn = api.get_db_connection()
    conn.execute(
        """INSERT INTO stations (entity_id, canonical_name, local_name, country, gem_wiki_url)
           VALUES ('station_agent', 'Wudongde hydroelectric plant', '乌东德水电站', 'China', 'https://www.gem.wiki/Wudongde_hydroelectric_plant')"""
    )
    conn.commit()
    conn.close()

    intent = TaskIntent(station_name="乌东德水电站", target_period="2024", query_hints=("乌东德 2024 年报",))
    candidate = {
        "url": "https://www.ctg.com.cn/reports/wudongde-2024.pdf", "canonical_url": "https://www.ctg.com.cn/reports/wudongde-2024.pdf",
        "link_text": "Wudongde hydroelectric plant 2024 annual generation report", "section_title": "中国三峡集团", "source_type": "official",
        "document_type": "pdf", "discovery_method": "deepseek_responses_web_search", "match_reason": "Wudongde hydroelectric plant 2024 annual generation",
    }
    with (
        patch("hydro_platform.config.llm_config.LLMConfig.get_deepseek_config", return_value={"api_key": "test-key", "model": "deepseek-v4-flash"}),
        patch("hydro_platform.intelligence.deepseek_agent.DeepSeekResponsesAgent.plan", return_value=intent),
        patch("hydro_platform.intelligence.deepseek_agent.DeepSeekResponsesAgent.search", return_value=[]),
        patch("hydro_platform.intelligence.web_search.WebSearchProvider.search", return_value=[{"url": candidate["url"], "title": candidate["link_text"], "publisher": candidate["section_title"]}]),
        patch("hydro_platform.intelligence.deepseek_agent.DeepSeekResponsesAgent.evaluate_search_results", return_value=[candidate]),
        patch("hydro_platform.discovery.official.OfficialSourceFinder.find", return_value=[]),
        patch("hydro_platform.discovery.url_probe.UrlProbe.probe_many", side_effect=_reachable),
    ):
        result = api.create_intelligent_task("收集乌东德水电站 2024 年发电量")

    assert result["success"] is True
    assert result["status"] == "ready"
    assert len(result["items"]) == 1
    conn = api.get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM intelligent_task_plans").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM intelligent_task_events").fetchone()[0] >= 3
    assert conn.execute("SELECT COUNT(*) FROM source_discoveries").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    conn.close()

    queued = api.create_collection_task_from_intelligent_plan(result["plan_id"], candidate["url"])
    assert queued["success"] is True
    conn = api.get_db_connection()
    task = conn.execute("SELECT source_type, user_specified_source FROM tasks").fetchone()
    assert tuple(task) == ("intelligent", candidate["url"])
    assert conn.execute("SELECT status FROM intelligent_task_plans").fetchone()[0] == "collection_queued"
    conn.close()


def test_intelligent_task_does_not_guess_an_unknown_station(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("test")
    api.initialize()
    intent = TaskIntent(station_name="不存在的水电站", target_period="2024")
    with (
        patch("hydro_platform.config.llm_config.LLMConfig.get_deepseek_config", return_value={"api_key": "test-key", "model": "deepseek-v4-flash"}),
        patch("hydro_platform.intelligence.deepseek_agent.DeepSeekResponsesAgent.plan", return_value=intent),
        patch("hydro_platform.intelligence.web_search.WebSearchProvider.search") as search,
    ):
        result = api.create_intelligent_task("收集一个不存在的水电站 2024 年发电量")

    assert result["success"] is True
    assert result["status"] == "needs_input"
    assert result["items"] == []
    search.assert_not_called()


def test_failed_intelligent_task_can_be_explicitly_restarted_with_saved_source(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("test")
    api.initialize()
    conn = api.get_db_connection()
    conn.execute(
        """INSERT INTO stations (entity_id, canonical_name, local_name, country)
           VALUES ('station_restart', 'Restart Dam', '重试水电站', 'China')"""
    )
    conn.commit()
    conn.close()

    created = api.create_task(
        "station_restart", "2024", source_type="intelligent",
        user_specified_source="https://example.test/restart.pdf",
    )
    assert created["success"] is True
    conn = api.get_db_connection()
    conn.execute(
        """UPDATE tasks SET status='failed', attempts=3, max_attempts=3,
           failure_stage='ACQUISITION_FAILED', last_error='old downloader issue'
           WHERE task_id=?""",
        (created["task_id"],),
    )
    conn.commit()
    conn.close()

    restarted = api.restart_intelligent_task(created["task_id"])

    assert restarted == {
        "success": True,
        "task_id": created["task_id"],
        "status": "pending",
        "source_url": "https://example.test/restart.pdf",
    }
    conn = api.get_db_connection()
    row = conn.execute(
        "SELECT status, attempts, source_type, user_specified_source, failure_stage FROM tasks WHERE task_id=?",
        (created["task_id"],),
    ).fetchone()
    conn.close()
    assert tuple(row) == ("pending", 0, "intelligent", "https://example.test/restart.pdf", None)
