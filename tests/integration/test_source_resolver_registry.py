"""来源解析优先级：历史来源必须在自动/受控发现之前被复用。"""

from types import SimpleNamespace

from hydro_platform.pipeline.source_resolver import resolve_sources_enhanced
from hydro_platform.registry.source_registry import SourceRegistry
from hydro_platform.common.enums import ContentKind


class _MustNotRunResolver:
    def resolve(self, task):  # pragma: no cover - 进入此处即说明优先级倒置
        raise AssertionError("已有有效历史来源时不应调用受控 fallback")


def test_historical_source_precedes_fallback(db):
    registry = SourceRegistry(db)
    registry.register_new_source(
        entity_id="station_history",
        source_url="https://example.test/station-history/2024",
        metadata={
            "covered_metric": "generation",
            "covered_year": 2024,
            "document_type": "html",
            "estimated_reliability": 0.8,
        },
    )
    task = SimpleNamespace(
        entity_id="station_history",
        target_period="2024",
        source_type="automatic",
        user_specified_source=None,
    )

    refs = resolve_sources_enhanced(db, task, fallback_resolver=_MustNotRunResolver())

    assert [ref.url for ref in refs] == ["https://example.test/station-history/2024"]
    assert refs[0].title.startswith("历史来源")
    assert refs[0].expected is ContentKind.ANY


def test_confirmed_intelligent_source_allows_router_to_detect_document_type(db):
    task = SimpleNamespace(
        entity_id="station_intelligent",
        target_period="2024",
        source_type="intelligent",
        user_specified_source="https://example.test/annual-report.pdf",
    )

    refs = resolve_sources_enhanced(db, task)

    assert [ref.url for ref in refs] == ["https://example.test/annual-report.pdf"]
    assert refs[0].expected is ContentKind.ANY
