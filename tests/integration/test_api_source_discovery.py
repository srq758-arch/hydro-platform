"""API 发现动作只产生候选台账，不能污染可信来源库。"""

from unittest.mock import patch

from hydro_platform.app.api import Api
from hydro_platform.discovery.official import SourceCandidate


def _probed(candidate: dict, *, access_status="reachable", http_status=200):
    """构造 URL 预检结果，避免 API 集成测试访问真实网络。"""
    return {
        **candidate,
        "access_status": access_status,
        "status": "discovered" if access_status != "unavailable" else "unavailable",
        "http_status": http_status,
        "final_url": candidate["url"],
        "error": None if access_status != "unavailable" else f"HTTP {http_status}",
    }


def test_api_discovers_and_records_candidates_without_creating_source(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("test")
    api.initialize()
    conn = api.get_db_connection()
    conn.execute(
        """INSERT INTO stations (entity_id, canonical_name, country, gem_wiki_url)
           VALUES ('station_api_discovery', 'API Dam', 'Exampleland', 'https://www.gem.wiki/API_Dam')"""
    )
    conn.commit()
    conn.close()

    candidate = SourceCandidate(
        url="https://operator.example/api-dam-2024-generation.pdf",
        canonical_url="https://operator.example/api-dam-2024-generation.pdf",
        source_type="official",
        document_type="pdf",
        match_reason="GEM Wiki「References」外链「Official report」",
        estimated_reliability=0.92,
        covered_year=2024,
        link_text="API Dam 2024 annual generation report",
        section_title="References",
        discovery_method="gem_wiki_external_link",
    )
    with (
        patch("hydro_platform.config.llm_config.LLMConfig.get_deepseek_config", return_value={"api_key": "test-key", "model": "deepseek-v4-flash"}),
        patch("hydro_platform.discovery.official.OfficialSourceFinder.find", return_value=[candidate]),
        patch("hydro_platform.intelligence.deepseek_agent.DeepSeekResponsesAgent.search", return_value=[]),
        patch("hydro_platform.intelligence.web_search.WebSearchProvider.search", return_value=[]),
        patch("hydro_platform.intelligence.deepseek_agent.DeepSeekResponsesAgent.evaluate_search_results", return_value=[]),
        patch("hydro_platform.discovery.url_probe.UrlProbe.probe_many", side_effect=lambda values: [_probed(value) for value in values]),
    ):
        result = api.discover_trusted_sources("station_api_discovery", "2024")

    assert result["success"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["status"] == "discovered"
    assert result["items"][0]["access_status"] == "reachable"
    assert result["recommendation"]["url"] == candidate.url
    conn = api.get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM source_discoveries").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    conn.close()


def test_api_hides_404_candidates_but_keeps_an_audit_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("test")
    api.initialize()
    conn = api.get_db_connection()
    conn.execute(
        """INSERT INTO stations (entity_id, canonical_name, country, gem_wiki_url)
           VALUES ('station_dead_link', 'Dead Link Dam', 'Exampleland', 'https://www.gem.wiki/Dead_Link_Dam')"""
    )
    conn.commit()
    conn.close()
    candidate = SourceCandidate(
        url="https://operator.example/dead-link-dam-2024-generation.pdf",
        canonical_url="https://operator.example/dead-link-dam-2024-generation.pdf",
        source_type="official", document_type="pdf", match_reason="GEM 外链",
        estimated_reliability=0.92, covered_year=2024, link_text="Dead Link Dam 2024 annual generation report",
        section_title="References", discovery_method="gem_wiki_external_link",
    )
    with (
        patch("hydro_platform.config.llm_config.LLMConfig.get_deepseek_config", return_value={"api_key": "test-key", "model": "deepseek-v4-flash"}),
        patch("hydro_platform.discovery.official.OfficialSourceFinder.find", return_value=[candidate]),
        patch("hydro_platform.intelligence.deepseek_agent.DeepSeekResponsesAgent.search", return_value=[]),
        patch("hydro_platform.intelligence.web_search.WebSearchProvider.search", return_value=[]),
        patch("hydro_platform.intelligence.deepseek_agent.DeepSeekResponsesAgent.evaluate_search_results", return_value=[]),
        patch(
            "hydro_platform.discovery.url_probe.UrlProbe.probe_many",
            side_effect=lambda values: [_probed(value, access_status="unavailable", http_status=404) for value in values],
        ),
    ):
        result = api.discover_trusted_sources("station_dead_link", "2024")

    assert result["success"] is True
    assert result["items"] == []
    assert "没有候选通过" in result["message"]
    conn = api.get_db_connection()
    row = conn.execute("SELECT access_status, http_status, status FROM source_discoveries").fetchone()
    assert tuple(row) == ("unavailable", 404, "unavailable")
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    conn.close()
