"""可选搜索通道只在凭据配置时运行，默认不产生网络调用。"""

from unittest.mock import patch

from hydro_platform.discovery.official import SourceCandidate
from hydro_platform.discovery.resolver import DiscoveryResolver


def test_google_search_is_used_only_when_explicitly_configured(db, monkeypatch):
    db.execute(
        "INSERT INTO stations (entity_id, canonical_name, country) VALUES ('station_google', 'Google Dam', 'Exampleland')"
    )
    db.commit()
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_SEARCH_ENGINE_ID", "test-cx")
    google_candidate = SourceCandidate(
        url="https://operator.example/annual-report-2024.pdf",
        source_type="official", document_type="pdf", match_reason="Google 搜索结果",
        estimated_reliability=0.9, covered_year=2024,
    )

    with patch("hydro_platform.discovery.google_search.GoogleSearchDiscovery.find", return_value=[google_candidate]) as find, \
         patch("hydro_platform.discovery.resolver.DeepSeekSourceFinder") as deepseek:
        deepseek.return_value.enabled = False
        resolver = DiscoveryResolver(db, deepseek_api_key=None)
        candidates = resolver.discover({
            "entity_id": "station_google", "entity_name": "Google Dam",
            "country": "Exampleland", "target_period": "2024", "metric": "generation",
        }, min_candidates=3)

    assert find.called
    assert any(item["url"] == "https://operator.example/annual-report-2024.pdf" for item in candidates)
