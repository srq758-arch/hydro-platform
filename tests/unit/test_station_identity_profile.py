"""Identity Profile 只能扩大可审计检索表达，不覆盖 seedlist 身份。"""

from hydro_platform.discovery.identity_profile import build_station_identity_profile
from hydro_platform.intelligence.deepseek_agent import TaskIntent
from hydro_platform.intelligence.source_discovery_service import (
    SourceDiscoveryRequest,
    SourceDiscoveryService,
)


class _NoDeepSeek:
    enabled = False


class _SearchCapture:
    last_diagnostics = []

    def __init__(self):
        self.queries = ()
        self.calls = []

    def search(self, queries):
        self.queries = tuple(queries)
        self.calls.append(self.queries)
        return []


class _Probe:
    def probe_many(self, values):
        return list(values)


def test_profile_keeps_seed_identity_and_uses_only_successful_official_domain_for_site_query(db):
    db.execute(
        """INSERT INTO stations(
               entity_id, canonical_name, local_name, aliases, country, operator, capacity_mw
           ) VALUES ('station-profile', 'Test River Hydropower Station', '长江测试水电站',
                     '测试电站;Test Dam', 'China', 'Test Power', 1200)"""
    )
    db.execute(
        """INSERT INTO sources(
               source_id, entity_id, url, source_url, canonical_url, source_type,
               success_count, last_success
           ) VALUES ('source-profile', 'station-profile', 'https://www.operator.example/reports/2023.pdf',
                     'https://www.operator.example/reports/2023.pdf',
                     'https://www.operator.example/reports/2023.pdf', 'official', 1,
                     '2026-09-14T00:00:00Z')"""
    )
    db.commit()
    station = dict(db.execute("SELECT * FROM stations WHERE entity_id='station-profile'").fetchone())

    profile = build_station_identity_profile(db, station)
    intent = SourceDiscoveryService.build_generation_intent(profile.station_context(), "2024")

    assert profile.canonical_name == "Test River Hydropower Station"
    assert profile.search_names[:2] == ("长江测试水电站", "测试电站")
    assert profile.official_domains == ("operator.example",)
    assert profile.official_entry_urls == ("https://www.operator.example/reports/2023.pdf",)
    assert intent.query_hints[0] == "测试电站 2024 完成发电量"
    assert "site:operator.example 测试电站 2024 发电量" in intent.query_hints

    search = _SearchCapture()
    response = SourceDiscoveryService(
        db, agent=_NoDeepSeek(), web_search=search, url_probe=_Probe(),
    ).discover(
        SourceDiscoveryRequest(
            entity_id="station-profile", target_period="2024",
            allowed_providers=frozenset({"program_controlled_search"}),
        ),
        intent=TaskIntent(
            station_name="任意输入名称", target_period="2024", metric="generation",
            query_hints=("模型补充查询",),
        ),
    )
    assert response.candidates == []
    assert search.calls[0][0] == "测试电站 2024 完成发电量"
    assert "site:operator.example 测试电站 2024 发电量" in search.calls[0]
    assert len(search.calls) == 2  # 空结果后只允许一次受控改写


def test_unaccepted_discovery_domain_cannot_become_official_site_constraint(db):
    db.execute(
        """INSERT INTO stations(entity_id, canonical_name, country)
           VALUES ('station-unaccepted', 'Unaccepted Dam', 'Exampleland')"""
    )
    db.execute(
        """INSERT INTO source_discoveries(
               discovery_id, entity_id, candidate_url, canonical_url, source_type,
               document_type, discovery_method, status, discovered_at, updated_at
           ) VALUES ('disc-unaccepted', 'station-unaccepted', 'https://random.example/report.pdf',
                     'https://random.example/report.pdf', 'official', 'pdf', 'search', 'discovered',
                     '2026-09-14T00:00:00Z', '2026-09-14T00:00:00Z')"""
    )
    db.commit()
    station = dict(db.execute("SELECT * FROM stations WHERE entity_id='station-unaccepted'").fetchone())

    profile = build_station_identity_profile(db, station)

    assert profile.official_domains == ()
    assert profile.official_entry_urls == ()
