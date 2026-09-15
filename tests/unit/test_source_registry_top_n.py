"""SourceRegistry 必须保留 Top-N 记忆并维持旧 best 接口。"""

from hydro_platform.registry.source_registry import SourceRegistry


def test_query_sources_returns_ranked_top_n_and_best_is_first(db):
    registry = SourceRegistry(db)
    entity_id = "station-top-n-unit"
    for index, score in enumerate((0.3, 0.9, 0.6), start=1):
        registry.register_new_source(
            entity_id=entity_id,
            source_url=f"https://source.test/{index}",
            metadata={
                "covered_metric": "generation",
                "covered_year": 2023,
                "estimated_reliability": score,
            },
        )

    sources = registry.query_sources(entity_id, "generation", 2023, limit=2)
    best = registry.query_best_source(entity_id, "generation", 2023)

    assert [item["source_reliability_score"] for item in sources] == [0.9, 0.6]
    assert best["source_id"] == sources[0]["source_id"]


def test_query_sources_zero_limit_is_empty_without_querying(db):
    assert SourceRegistry(db).query_sources("station", "generation", 2024, limit=0) == []
