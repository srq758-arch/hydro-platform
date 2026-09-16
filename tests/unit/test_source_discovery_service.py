"""Search V2 统一 Discovery 服务的行为测试。"""

from hydro_platform.intelligence.source_discovery_service import (
    SourceDiscoveryRequest,
    SourceDiscoveryService,
    TaskSourceDiscoveryAdapter,
)


class _NoDeepSeek:
    """无模型时程序搜索仍必须可用。"""

    enabled = False


class _ProgramSearch:
    def __init__(self):
        self.calls = []
        self.last_diagnostics = [{"provider": "DuckDuckGo", "status": "ok", "count": 1}]

    def search(self, queries):
        self.calls.append(tuple(queries))
        return [{
            "url": "https://publisher.example/notice-2024.html",
            "title": "测试水电站 2024 年全年发电量公告",
            "snippet": "测试水电站 2024 年全年发电量为 100 亿千瓦时。",
            "publisher": "publisher.example",
            "search_engine": "DuckDuckGo",
            "query": next(iter(queries)),
        }]


class _ProgramSearchWithMetrics(_ProgramSearch):
    last_metrics = {
        "providers": {
            "DuckDuckGo": {"calls": 1, "successes": 1, "empty": 0, "failures": 0, "estimated_cost": 0.2},
        },
        "estimated_cost": 0.2,
    }


class _Probe:
    def probe_many(self, values):
        return [{
            **value,
            "access_status": "reachable",
            "status": "discovered",
            "http_status": 200,
            "final_url": value["url"],
            "error": None,
            "metadata": {
                **(value.get("metadata") or {}),
                "content_preview": "测试水电站 2024 年全年发电量为 100 亿千瓦时。",
            },
        } for value in values]


class _OfficialExplorer:
    def __init__(self):
        self.calls = []

    def discover(self, **kwargs):
        self.calls.append(kwargs)
        return [{
            "url": "https://operator.example/files/2024-generation.pdf",
            "canonical_url": "https://operator.example/files/2024-generation.pdf",
            "link_text": "2024 年发电量年度报告",
            "source_type": "official", "document_type": "pdf",
            "discovery_method": "official_site_navigation",
            "metadata": {"parent_url": "https://operator.example/reports", "discovery_depth": 1},
        }]


def _task(db):
    db.execute(
        """INSERT INTO stations(entity_id, canonical_name, local_name, country)
           VALUES ('station_service', 'Test Hydropower Station', '测试水电站', 'China')"""
    )
    db.execute(
        """INSERT INTO tasks(
               task_id, entity_id, entity_type, task_type, target_period,
               status, created_at, updated_at
           ) VALUES ('task-service', 'station_service', 'station', 'station_generation',
                     '2024', 'pending', '2026-09-14T00:00:00Z', '2026-09-14T00:00:00Z')"""
    )
    db.commit()


def test_single_service_runs_program_search_without_deepseek_and_persists_lineage(db):
    _task(db)
    search = _ProgramSearch()
    service = SourceDiscoveryService(
        db, agent=_NoDeepSeek(), web_search=search, url_probe=_Probe(),
    )
    response = service.discover(SourceDiscoveryRequest(
        entity_id="station_service", target_period="2024", task_id="task-service",
        allowed_providers=frozenset({"program_controlled_search"}),
    ))

    assert search.calls  # 程序搜索真实被服务调用，而非只检查配置/文件。
    assert len(response.candidates) == 1
    assert response.candidates[0].url == "https://publisher.example/notice-2024.html"
    assert response.candidates[0].lead_id
    assert response.warnings == []
    assert response.provider_diagnostics == [{"provider": "DuckDuckGo", "status": "ok", "count": 1}]
    row = db.execute(
        """SELECT lead.provider, lead.status, candidate.lead_id
           FROM search_leads lead
           JOIN candidate_sources candidate ON candidate.lead_id=lead.lead_id
           WHERE candidate.task_id='task-service'"""
    ).fetchone()
    assert tuple(row) == ("DuckDuckGo", "normalized", response.candidates[0].lead_id)


def test_network_disabled_returns_explicit_diagnostic_without_calling_provider(db):
    _task(db)
    search = _ProgramSearch()
    service = SourceDiscoveryService(
        db, agent=_NoDeepSeek(), web_search=search, url_probe=_Probe(),
    )
    response = service.discover(SourceDiscoveryRequest(
        entity_id="station_service", target_period="2024", network_allowed=False,
    ))

    assert search.calls == []
    assert response.candidates == []
    assert response.provider_diagnostics == [{"provider": "network", "status": "disabled", "count": 0}]


def test_build_intent_uses_portuguese_queries_for_brazil_seed():
    intent = SourceDiscoveryService.build_intent(
        {
            "canonical_name": "Belo Monte hydroelectric plant",
            "local_name": "Usina Hidrelétrica Belo Monte",
            "country": "Brazil",
            "operator": "Norte Energia",
        },
        "2024",
    )

    assert intent.query_hints == (
        "Belo Monte 2024 geração anual",
        "Belo Monte 2024 relatório anual geração",
        "Norte Energia 2024 geração Belo Monte",
    )


def test_build_intent_uses_turkish_queries_on_first_search():
    intent = SourceDiscoveryService.build_intent(
        {
            "canonical_name": "Ataturk Dam",
            "local_name": "Atatürk Barajı",
            "country": "Turkey",
            "operator": "Elektrik Üretim AS (EÜAŞ)",
        },
        "2022",
    )

    assert intent.query_hints == (
        '"Atatürk Barajı" 2022 yıllık elektrik üretimi',
        '"Atatürk Barajı" 2022 yıllık faaliyet raporu üretim',
        '"Elektrik Üretim AS (EÜAŞ)" 2022 yıllık üretim raporu "Atatürk Barajı"',
    )


def test_build_intent_uses_arabic_queries_on_first_search():
    intent = SourceDiscoveryService.build_intent(
        {
            "canonical_name": "Aswan High Dam",
            "local_name": "السد العالي",
            "country": "Egypt",
            "operator": "Egyptian Electricity Holding Co",
        },
        "2022",
    )

    assert intent.query_hints == (
        '"السد العالي" 2022 إنتاج الكهرباء السنوي',
        '"السد العالي" 2022 التقرير السنوي إنتاج الكهرباء',
        '"Egyptian Electricity Holding Co" 2022 التقرير السنوي إنتاج "السد العالي"',
    )


def test_pipeline_adapter_returns_same_unified_candidates(db):
    _task(db)
    search = _ProgramSearch()
    adapter = TaskSourceDiscoveryAdapter(SourceDiscoveryService(
        db, agent=_NoDeepSeek(), web_search=search, url_probe=_Probe(),
    ))

    candidates = adapter.discover({
        "task_id": "task-service", "entity_id": "station_service", "target_period": "2024",
        "metric": "generation",
    }, max_candidates=5)

    assert search.calls
    assert adapter.last_response is not None
    assert candidates == adapter.last_response.candidates
    assert any(item.url == "https://publisher.example/notice-2024.html" for item in candidates)
    assert any(item.lead_id for item in candidates)


def test_service_exposes_program_search_metrics_as_a_diagnostic(db):
    _task(db)
    search = _ProgramSearchWithMetrics()
    response = SourceDiscoveryService(
        db, agent=_NoDeepSeek(), web_search=search, url_probe=_Probe(),
    ).discover(SourceDiscoveryRequest(
        entity_id="station_service", target_period="2024", task_id="task-service",
        allowed_providers=frozenset({"program_controlled_search"}),
    ))

    metrics = next(item for item in response.provider_diagnostics if item.get("status") == "metrics")
    assert metrics["provider"] == "program_controlled_search"
    assert metrics["metrics"]["estimated_cost"] == 0.2


def test_service_uses_only_verified_profile_domain_for_official_site_explorer(db):
    _task(db)
    db.execute(
        """INSERT INTO sources(
               source_id, entity_id, url, source_url, canonical_url, source_type,
               success_count, last_success
           ) VALUES ('official-success', 'station_service',
                     'https://operator.example/old-report.pdf',
                     'https://operator.example/old-report.pdf',
                     'https://operator.example/old-report.pdf', 'official', 1,
                     '2026-09-14T00:00:00Z')"""
    )
    db.commit()
    explorer = _OfficialExplorer()
    response = SourceDiscoveryService(
        db, agent=_NoDeepSeek(), web_search=_ProgramSearch(), url_probe=_Probe(),
        official_site_explorer=explorer,
    ).discover(SourceDiscoveryRequest(
        entity_id="station_service", target_period="2024",
        allowed_providers=frozenset({"official_site_explorer"}),
    ))

    assert explorer.calls == [{
        "official_domains": ["operator.example"],
        "official_entry_urls": ["https://operator.example/old-report.pdf"],
        "known_report_paths": {},
        "target_period": "2024",
    }]
    assert [item.url for item in response.candidates] == ["https://operator.example/files/2024-generation.pdf"]
    assert response.provider_diagnostics == [{
        "provider": "official_site_explorer", "status": "ok", "count": 1,
    }]


def test_service_does_not_explore_when_profile_has_no_verified_official_domain(db):
    _task(db)
    explorer = _OfficialExplorer()
    response = SourceDiscoveryService(
        db, agent=_NoDeepSeek(), web_search=_ProgramSearch(), url_probe=_Probe(),
        official_site_explorer=explorer,
    ).discover(SourceDiscoveryRequest(
        entity_id="station_service", target_period="2024",
        allowed_providers=frozenset({"official_site_explorer"}),
    ))

    assert explorer.calls == []
    assert response.candidates == []
    assert response.provider_diagnostics == [{
        "provider": "official_site_explorer", "status": "skipped", "count": 0,
        "reason": "尚无历史成功或人工接受的官方域名",
    }]
