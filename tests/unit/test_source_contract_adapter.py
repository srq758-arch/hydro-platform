"""B1 旧来源入口必须单向归一化为 CandidateSource。"""

from types import SimpleNamespace

from hydro_platform.common.enums import ContentKind
from hydro_platform.discovery.official import SourceCandidate
from hydro_platform.models.source_pipeline import CandidateSource
from hydro_platform.pipeline.context import SourceRef
from hydro_platform.pipeline.source_contract_adapter import (
    normalize_candidate_sources,
    source_task_id,
    to_candidate_source,
)


def test_source_ref_is_normalized_without_guessing_content_type():
    candidate = to_candidate_source(
        SourceRef(
            url="https://operator.test/report",
            expected=ContentKind.HTML,
            title="Annual report",
        ),
        task_id="task-1",
        discovery_method="injected_resolver",
    )
    assert isinstance(candidate, CandidateSource)
    assert candidate.expected_content_kind is ContentKind.HTML
    assert candidate.expected is ContentKind.HTML
    assert candidate.discovery_method == "injected_resolver"


def test_discovery_dict_preserves_method_score_and_unmodeled_audit_metadata():
    candidate = to_candidate_source(
        {
            "url": "https://operator.test/report.pdf",
            "canonical_url": "https://operator.test/report.pdf?version=1",
            "title": "2023 report",
            "source_type": "official",
            "document_type": "pdf",
            "discovery_method": "program_search_result",
            "combined_score": 0.91,
            "match_reason": "entity, year and metric matched",
            "metadata": {"search_provider": "test-search"},
        },
        task_id="task-1",
    )
    assert candidate.discovery_method == "program_search_result"
    assert candidate.priority_score == 0.91
    # document_type is a clue, not an acquisition constraint.
    assert candidate.expected_content_kind is ContentKind.ANY
    assert candidate.metadata["match_reason"] == "entity, year and metric matched"
    assert candidate.metadata["search_provider"] == "test-search"
    assert "metadata" not in candidate.metadata


def test_official_candidate_and_registry_row_share_one_output_contract():
    official = SourceCandidate(
        url="https://operator.test/a",
        source_type="official",
        document_type="html",
        match_reason="official site",
        estimated_reliability=0.8,
        discovery_method="gem_wiki_external_link",
    )
    registry = {
        "source_url": "https://operator.test/b",
        "canonical_url": "https://operator.test/b",
        "source_type": "official",
        "source_reliability_score": 0.7,
        "document_type": "pdf",
    }
    results = [
        to_candidate_source(official, task_id="task-1"),
        to_candidate_source(
            registry,
            task_id="task-1",
            discovery_method="source_registry",
        ),
    ]
    assert all(isinstance(item, CandidateSource) for item in results)
    assert [item.discovery_method for item in results] == [
        "gem_wiki_external_link",
        "source_registry",
    ]


def test_normalization_deduplicates_canonical_urls_in_ranked_order():
    sources = [
        {"url": "https://example.test/report/", "combined_score": 0.9},
        {"url": "https://EXAMPLE.test/report", "combined_score": 0.8},
        {"url": "https://example.test/other", "combined_score": 0.7},
    ]
    normalized = normalize_candidate_sources(
        sources,
        task_id="task-1",
        discovery_method="test_provider",
    )
    assert [item.url for item in normalized] == [
        "https://example.test/report/",
        "https://example.test/other",
    ]


def test_real_task_id_is_used_and_legacy_test_object_gets_stable_fallback():
    assert source_task_id(SimpleNamespace(task_id="task-real")) == "task-real"
    legacy = SimpleNamespace(entity_id="station-1", target_period="2023")
    assert source_task_id(legacy) == "legacy::station-1::2023"
