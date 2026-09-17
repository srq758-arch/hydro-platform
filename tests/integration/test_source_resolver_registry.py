"""来源解析优先级：历史来源必须在自动/受控发现之前被复用。"""

from types import SimpleNamespace

from hydro_platform.pipeline.source_resolver import resolve_sources_enhanced
from hydro_platform.registry.source_registry import SourceRegistry
from hydro_platform.common.enums import ContentKind
from hydro_platform.models.source_pipeline import CandidateSource


class _MustNotRunResolver:
    def __init__(self):
        self.called = False

    def resolve(self, task):  # pragma: no cover - 进入此处即说明优先级倒置
        self.called = True
        raise AssertionError("已有有效历史来源时不应调用受控 fallback")


class _DiscoveryResolver:
    def __init__(self, values):
        self.values = values

    def discover(self, task, min_candidates=3, max_candidates=5):
        return self.values


def test_historical_source_precedes_fallback(db):
    registry = SourceRegistry(db)
    source_id = registry.register_new_source(
        entity_id="station_history",
        source_url="https://example.test/station-history/2024",
        metadata={
            "covered_metric": "generation",
            "covered_year": 2024,
            "document_type": "html",
            "estimated_reliability": 0.8,
        },
    )
    registry.update_success(source_id, document_id="doc-history")
    task = SimpleNamespace(
        entity_id="station_history",
        target_period="2024",
        source_type="automatic",
        user_specified_source=None,
    )

    fallback = _MustNotRunResolver()
    refs = resolve_sources_enhanced(db, task, fallback_resolver=fallback)

    assert [ref.url for ref in refs] == ["https://example.test/station-history/2024"]
    assert isinstance(refs[0], CandidateSource)
    assert refs[0].discovery_method == "source_registry"
    assert refs[0].title.startswith("历史来源")
    assert refs[0].expected is ContentKind.ANY
    assert fallback.called is False


def test_confirmed_intelligent_source_allows_router_to_detect_document_type(db):
    task = SimpleNamespace(
        entity_id="station_intelligent",
        target_period="2024",
        source_type="intelligent",
        user_specified_source="https://example.test/annual-report.pdf",
    )

    refs = resolve_sources_enhanced(db, task)

    assert [ref.url for ref in refs] == ["https://example.test/annual-report.pdf"]
    assert isinstance(refs[0], CandidateSource)
    assert refs[0].discovery_method == "user_confirmed_url"
    assert refs[0].expected is ContentKind.ANY


def test_discovery_channels_are_normalized_to_candidate_sources(db):
    db.execute(
        """INSERT INTO stations(entity_id, entity_type, canonical_name)
           VALUES ('station-discovery-contract', 'station', 'Contract Dam')"""
    )
    task = SimpleNamespace(
        task_id="task-discovery-contract",
        entity_id="station-discovery-contract",
        target_period="2024",
        source_type="automatic",
        user_specified_source=None,
    )
    discovered = [
        {
            "url": "https://operator.test/report.pdf",
            "canonical_url": "https://operator.test/report.pdf",
            "source_type": "official",
            "document_type": "pdf",
            "discovery_method": "deepseek_native_search",
            "combined_score": 0.88,
        },
        {
            "url": "https://search.test/result",
            "source_type": "reference",
            "discovery_method": "program_search_result",
            "combined_score": 0.72,
        },
        {
            "url": "https://gem-link.test/result",
            "source_type": "reference",
            "discovery_method": "gem_wiki_external_link",
            "combined_score": 0.6,
        },
    ]

    refs = resolve_sources_enhanced(
        db,
        task,
        discovery_resolver=_DiscoveryResolver(discovered),
    )

    assert all(isinstance(ref, CandidateSource) for ref in refs)
    assert [ref.discovery_method for ref in refs] == [
        "deepseek_native_search",
        "program_search_result",
        "gem_wiki_external_link",
    ]
    assert all(ref.task_id == task.task_id for ref in refs)
    assert all(ref.expected is ContentKind.ANY for ref in refs)


def test_registry_returns_top_n_and_skips_expired_candidate(db):
    registry = SourceRegistry(db)
    entity_id = "station-registry-topn"
    values = [
        ("https://history.test/high", 0.95),
        ("https://history.test/medium", 0.8),
        ("https://history.test/low", 0.6),
    ]
    ids = []
    for url, score in values:
        source_id = registry.register_new_source(
            entity_id=entity_id,
            source_url=url,
            metadata={
                "covered_metric": "generation",
                "covered_year": 2024,
                "source_type": "reference",
                "estimated_reliability": score,
            },
        )
        # Only verified historical sources participate in task reuse.
        if url != "https://history.test/high":
            registry.update_success(source_id, document_id=f"doc-{url.rsplit('/', 1)[-1]}")
        ids.append(source_id)
    # Highest-ranked source has not succeeded for over 90 days and must not
    # suppress the remaining valid historical candidates.
    db.execute(
        "UPDATE sources SET last_success='2020-01-01T00:00:00Z' WHERE source_id=?",
        (ids[0],),
    )
    db.commit()
    task = SimpleNamespace(
        task_id="task-registry-topn",
        entity_id=entity_id,
        target_period="2024",
        source_type="automatic",
        user_specified_source=None,
    )

    refs = resolve_sources_enhanced(db, task)

    assert [ref.url for ref in refs] == [
        "https://history.test/medium",
        "https://history.test/low",
    ]
    assert all(ref.discovery_method == "source_registry" for ref in refs)


def test_unverified_registry_source_does_not_mask_discovery(db):
    registry = SourceRegistry(db)
    source_id = registry.register_new_source(
        entity_id="station-unverified",
        source_url="https://history.test/not-yet-verified",
        metadata={
            "covered_metric": "generation",
            "covered_year": 2024,
            "source_type": "reference",
            "estimated_reliability": 0.99,
        },
    )
    # Deliberately leave success_count=0/last_success=NULL: this is the state
    # after a candidate has been discovered or downloaded but not validated.
    assert tuple(db.execute(
        "SELECT success_count, last_success FROM sources WHERE source_id=?",
        (source_id,),
    ).fetchone()) == (0, None)
    task = SimpleNamespace(
        task_id="task-unverified",
        entity_id="station-unverified",
        target_period="2024",
        source_type="automatic",
        user_specified_source=None,
    )
    discovered = [{
        "url": "https://search.test/verified-new",
        "source_type": "official",
        "discovery_method": "program_search_result",
    }]

    refs = resolve_sources_enhanced(
        db,
        task,
        discovery_resolver=_DiscoveryResolver(discovered),
    )

    assert [ref.url for ref in refs] == ["https://search.test/verified-new"]
    assert refs[0].discovery_method == "program_search_result"


def test_registry_source_recovers_after_old_failures_but_not_recent_failures(db):
    registry = SourceRegistry(db)
    source_id = registry.register_new_source(
        entity_id="station-failure-recovery",
        source_url="https://history.test/recoverable",
        metadata={
            "covered_metric": "generation",
            "covered_year": 2024,
            "source_type": "reference",
            "estimated_reliability": 0.8,
        },
    )
    registry.update_success(source_id, document_id="doc-recoverable")
    db.execute(
        """UPDATE sources
           SET failure_count=3, last_failure='2020-01-01T00:00:00Z'
           WHERE source_id=?""",
        (source_id,),
    )
    db.commit()
    task = SimpleNamespace(
        task_id="task-failure-recovery",
        entity_id="station-failure-recovery",
        target_period="2024",
        source_type="automatic",
        user_specified_source=None,
    )

    # An old ISO timestamp must be eligible again after the seven-day window.
    refs = resolve_sources_enhanced(db, task)
    assert [ref.url for ref in refs] == ["https://history.test/recoverable"]

    db.execute(
        """UPDATE sources
           SET last_failure=datetime('now'), failure_count=3
           WHERE source_id=?""",
        (source_id,),
    )
    db.commit()
    refs = resolve_sources_enhanced(
        db,
        task,
        discovery_resolver=_DiscoveryResolver([{
            "url": "https://search.test/recovery-refresh",
            "source_type": "official",
            "discovery_method": "program_search_result",
        }]),
    )
    assert [ref.url for ref in refs] == ["https://search.test/recovery-refresh"]


def test_stale_top_sources_do_not_hide_healthy_source_after_limit(db):
    registry = SourceRegistry(db)
    entity_id = "station-stale-top-five"
    source_ids = []
    for index in range(6):
        source_id = registry.register_new_source(
            entity_id=entity_id,
            source_url=f"https://history.test/stale-{index}",
            metadata={
                "covered_metric": "generation",
                "covered_year": 2024,
                "source_type": "reference",
                "estimated_reliability": 0.95 - index * 0.01,
            },
        )
        registry.update_success(source_id, document_id=f"doc-stale-{index}")
        source_ids.append(source_id)
    db.execute(
        """UPDATE sources SET last_success='2020-01-01T00:00:00Z'
           WHERE source_id IN (?, ?, ?, ?, ?)""",
        tuple(source_ids[:5]),
    )
    db.commit()
    task = SimpleNamespace(
        task_id="task-stale-top-five",
        entity_id=entity_id,
        target_period="2024",
        source_type="automatic",
        user_specified_source=None,
    )

    refs = resolve_sources_enhanced(db, task)

    assert [ref.url for ref in refs] == ["https://history.test/stale-5"]
