"""可选搜索通道只在凭据配置时运行，默认不产生网络调用。"""

from unittest.mock import patch

from hydro_platform.discovery.official import SourceCandidate
from hydro_platform.discovery.resolver import DiscoveryResolver
from hydro_platform.models.source_pipeline import CandidateSource


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
    assert all(isinstance(item, CandidateSource) for item in candidates)
    assert any(item.url == "https://operator.example/annual-report-2024.pdf" for item in candidates)


def test_every_configured_discovery_channel_runs_even_when_official_has_enough_candidates(db, monkeypatch):
    """不能因 URL 模板数量达到 min_candidates 就跳过真实检索通道。"""
    db.execute(
        "INSERT INTO stations (entity_id, canonical_name, country) VALUES ('station_multi', 'Multi Dam', 'China')"
    )
    db.commit()
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_SEARCH_ENGINE_ID", "test-cx")

    def candidate(url: str, source_type: str = "official") -> SourceCandidate:
        return SourceCandidate(
            url=url, source_type=source_type, document_type="html",
            match_reason="test", estimated_reliability=0.8, covered_year=2024,
        )

    with patch("hydro_platform.discovery.resolver.OfficialSourceFinder.find", return_value=[
        candidate("https://official.example/one"),
        candidate("https://official.example/two"),
        candidate("https://official.example/three"),
    ]) as official, patch(
        "hydro_platform.discovery.resolver.AuthoritySourceFinder.find",
        return_value=[candidate("https://authority.example/data", "authority")],
    ) as authority, patch(
        "hydro_platform.discovery.google_search.GoogleSearchDiscovery.find",
        return_value=[candidate("https://search.example/report", "search_result")],
    ) as google, patch("hydro_platform.discovery.resolver.DeepSeekSourceFinder") as deepseek:
        deepseek.return_value.enabled = True
        deepseek.return_value.find.return_value = [{
            "url": "https://deepseek.example/report", "source_type": "reference",
            "document_type": "html", "match_reason": "DeepSeek", "title": "DeepSeek report",
        }]
        resolver = DiscoveryResolver(db, deepseek_api_key="test-key")
        candidates = resolver.discover({
            "entity_id": "station_multi", "entity_name": "Multi Dam", "country": "China",
            "target_period": "2024", "metric": "generation",
        }, min_candidates=1, max_candidates=10)

    assert official.called
    assert authority.called
    assert google.called
    assert deepseek.return_value.find.called
    assert {item.url for item in candidates} >= {
        "https://official.example/one", "https://authority.example/data",
        "https://search.example/report", "https://deepseek.example/report",
    }
    assert {(item["provider"], item["status"]) for item in resolver.last_diagnostics} >= {
        ("official_gem", "ok"), ("authority", "ok"),
        ("google_custom_search", "ok"), ("deepseek_native_web_search", "ok"),
    }


def test_real_task_search_results_keep_lead_and_candidate_lineage(db, monkeypatch):
    """自动任务的 Google 原始结果必须保存为 SearchLead，再被候选引用。"""
    db.execute(
        "INSERT INTO stations (entity_id, canonical_name, country) VALUES ('station_lineage', 'Lineage Dam', 'China')"
    )
    db.execute(
        """INSERT INTO tasks(
               task_id, entity_id, entity_type, task_type, target_period,
               status, created_at, updated_at
           ) VALUES ('task-lineage', 'station_lineage', 'station', 'station_generation',
                     '2024', 'pending', '2026-09-14T00:00:00Z', '2026-09-14T00:00:00Z')"""
    )
    db.commit()
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_SEARCH_ENGINE_ID", "test-cx")
    google_candidate = SourceCandidate(
        url="https://operator.example/lineage-report-2024.html", source_type="search_result",
        document_type="html", match_reason="Google test", estimated_reliability=0.7, covered_year=2024,
    )

    with patch("hydro_platform.discovery.resolver.OfficialSourceFinder.find", return_value=[]), patch(
        "hydro_platform.discovery.resolver.AuthoritySourceFinder.find", return_value=[]
    ), patch(
        "hydro_platform.discovery.google_search.GoogleSearchDiscovery.find", return_value=[google_candidate]
    ), patch("hydro_platform.discovery.resolver.DeepSeekSourceFinder") as deepseek:
        deepseek.return_value.enabled = False
        candidates = DiscoveryResolver(db).discover({
            "task_id": "task-lineage", "entity_id": "station_lineage", "entity_name": "Lineage Dam",
            "target_period": "2024", "metric": "generation",
        }, max_candidates=5)

    stored = next(item for item in candidates if item.url == google_candidate.url)
    assert stored.lead_id
    row = db.execute(
        """SELECT lead.url, lead.status, candidate.lead_id
           FROM candidate_sources candidate
           JOIN search_leads lead ON lead.lead_id = candidate.lead_id
           WHERE candidate.task_id='task-lineage' AND candidate.url=?""",
        (google_candidate.url,),
    ).fetchone()
    assert tuple(row) == (google_candidate.url, "normalized", stored.lead_id)
