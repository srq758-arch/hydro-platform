"""统一可信来源发现：多通道融合后必须以任务相关性为硬门槛。"""

from unittest.mock import Mock, patch

from hydro_platform.discovery.relevance import CandidateRelevanceVerifier
from hydro_platform.app.api import Api
from hydro_platform.intelligence.deepseek_agent import TaskIntent
from hydro_platform.intelligence.search_aggregator import SearchAggregator
from hydro_platform.intelligence.trusted_source_discovery import TrustedSourceDiscovery
from hydro_platform.models.source_pipeline import CandidateSource


def test_url_canonicalization_strips_tracking_noise_but_preserves_business_query():
    assert TrustedSourceDiscovery.canonicalize_url(
        "HTTPS://Publisher.Example:443/reports//three-gorges-2024/?utm_source=search&year=2024#table"
    ) == "https://publisher.example/reports/three-gorges-2024?year=2024"
    assert TrustedSourceDiscovery.canonicalize_url(
        "https://publisher.example/download?id=2024&token=abc/"
    ) == "https://publisher.example/download?id=2024&token=abc%2F"


def test_deduplicate_collapses_url_variants_and_keeps_original_url_for_audit():
    values = [
        {"url": "https://publisher.example/report/?utm_medium=search", "title": "first"},
        {"url": "https://PUBLISHER.example/report#page=2", "title": "duplicate"},
    ]
    merged = TrustedSourceDiscovery._deduplicate(values)
    assert len(merged) == 1
    assert merged[0]["url"] == values[0]["url"]
    assert merged[0]["canonical_url"] == "https://publisher.example/report"
    assert merged[0]["metadata"]["publisher_domain"] == "publisher.example"


def test_search_aggregator_prefers_redirect_target_and_keeps_entry_alias():
    merged = SearchAggregator.merge([
        {
            "url": "https://short.example/go?id=42",
            "canonical_url": "https://short.example/go?id=42",
            "final_url": "https://publisher.example/reports/annual/?utm_source=search#page=3",
            "access_status": "reachable",
        },
        {
            "url": "https://publisher.example/reports/annual",
            "canonical_url": "https://publisher.example/reports/annual",
            "final_url": "https://publisher.example/reports/annual",
            "access_status": "reachable",
        },
    ], prefer_final=True)

    assert len(merged) == 1
    assert merged[0]["canonical_url"] == "https://publisher.example/reports/annual"
    assert "https://short.example/go?id=42" in merged[0]["metadata"]["alias_urls"]
    assert merged[0]["metadata"]["publisher_domain"] == "publisher.example"


def test_search_aggregator_keeps_deepseek_enrichment_for_duplicate_program_url():
    url = "https://publisher.example/reports/three-gorges-2024.pdf"
    merged = SearchAggregator.merge([
        {
            "url": url,
            "source_type": "reference",
            "discovery_method": "program_search_result",
            "link_text": "搜索结果",
            "match_reason": "程序搜索结果；需人工核实",
            "metadata": {"query": "三峡 2024 发电量"},
        },
        {
            "url": url,
            "source_type": "official",
            "discovery_method": "deepseek_planned_web_search",
            "link_text": "长江电力 2024 年发电量公告",
            "match_reason": "DeepSeek 基于程序搜索结果判定为运营方官方公告",
            "metadata": {"from_deepseek": True},
        },
    ])

    assert len(merged) == 1
    assert merged[0]["url"] == url
    assert merged[0]["source_type"] == "official"
    assert merged[0]["discovery_method"] == "deepseek_planned_web_search"
    assert "DeepSeek" in merged[0]["match_reason"]
    assert merged[0]["metadata"]["query"] == "三峡 2024 发电量"
    assert merged[0]["metadata"]["from_deepseek"] is True


def test_search_aggregator_publisher_summary_is_grouped_and_sorted():
    summary = SearchAggregator.publisher_summary([
        {"url": "https://b.example/one", "source_type": "reference"},
        {"url": "https://a.example/one", "source_type": "official"},
        {"url": "https://a.example/two", "source_type": "authority"},
    ])
    assert summary == [
        {"publisher_domain": "a.example", "count": 2, "source_types": ["authority", "official"]},
        {"publisher_domain": "b.example", "count": 1, "source_types": ["reference"]},
    ]


def _candidate(url: str, title: str, *, method: str, reason: str = ""):
    return {
        "url": url, "canonical_url": url, "link_text": title,
        "section_title": "Official publisher", "source_type": "official",
        "document_type": "pdf", "discovery_method": method,
        "match_reason": reason or title,
    }


def test_relevance_rejects_accessible_but_irrelvant_safety_notice():
    result = CandidateRelevanceVerifier().verify(
        _candidate(
            "https://nea.example/2021/safety-notice.html",
            "2021年全国水电站大坝管理单位安全责任人名单",
            method="gem_wiki_external_link",
        ),
        station={"canonical_name": "Three Gorges Dam", "local_name": "三峡电站", "aliases": "三峡水电站"},
        target_period="2023",
    )

    assert result.eligible is False
    assert "安全责任" in result.reason


def test_relevance_accepts_target_station_year_and_annual_generation_evidence():
    result = CandidateRelevanceVerifier().verify(
        _candidate(
            "https://disclosure.example/2024/three-gorges-2023-report.pdf",
            "长江电力2023年年度报告：三峡电站年发电量802.71亿千瓦时",
            method="deepseek_planned_web_search",
        ),
        station={"canonical_name": "Three Gorges Dam", "local_name": "三峡电站", "aliases": "三峡水电站"},
        target_period="2023",
    )

    assert result.eligible is True
    assert result.score >= 0.9
    assert result.period_scope == "annual"
    assert "全年口径已确认" in result.reason


def test_relevance_rejects_quarterly_generation_even_when_year_and_station_match():
    result = CandidateRelevanceVerifier().verify(
        _candidate(
            "https://disclosure.example/three-gorges-2023-q3.html",
            "三峡电站 2023 年三季度发电量 100 亿千瓦时",
            method="program_search_result",
        ),
        station={"canonical_name": "Three Gorges Dam", "local_name": "三峡电站", "aliases": None},
        target_period="2023",
    )

    assert result.eligible is False
    assert result.period_scope == "partial"
    assert "非全年" in result.reason


def test_relevance_rejects_quarterly_article_when_unrelated_annual_word_appears_later():
    result = CandidateRelevanceVerifier().verify(
        _candidate(
            "https://news.example/three-gorges-2025-q1.html",
            "三峡电站一季度发电量达148亿千瓦时",
            method="program_search_result",
            reason=(
                "2025年三峡电站一季度发电量达148亿千瓦时。"
                "年度枯水期调度工作同时持续开展。"
            ),
        ),
        station={"canonical_name": "Three Gorges Dam", "local_name": "三峡电站", "aliases": None},
        target_period="2025",
    )

    assert result.eligible is False
    assert result.period_scope == "partial"
    assert "一季度" in result.reason


def test_relevance_requires_year_and_annual_scope_near_generation_evidence():
    result = CandidateRelevanceVerifier().verify(
        _candidate(
            "https://disclosure.example/three-gorges.html",
            "三峡电站完成发电量 802.71 亿千瓦时",
            method="program_search_result",
            reason="2023年三峡工程全年运行情况总体良好，三峡电站完成发电量802.71亿千瓦时。",
        ),
        station={"canonical_name": "Three Gorges Dam", "local_name": "三峡电站", "aliases": None},
        target_period="2023",
    )

    assert result.eligible is True
    assert result.period_scope == "annual"
    assert "2023年三峡工程全年运行情况总体良好" in result.evidence
    assert "802.71亿千瓦时" in result.evidence


def test_engine_merges_native_program_and_gem_but_returns_only_qualified_candidates():
    valid = _candidate(
        "https://disclosure.example/three-gorges-2023.pdf",
        "三峡电站2023年年度发电量报告",
        method="deepseek_responses_web_search",
    )
    irrelevant = _candidate(
        "https://nea.example/safety-2021.html",
        "2021年三峡水电站安全责任人名单",
        method="gem_wiki_external_link",
    )
    agent = Mock()
    agent.suggest_search_queries.return_value = ("三峡工程 2023 年全年发电量", "长江电力 2023 三峡电站 年度报告")
    agent.search.return_value = [valid]
    agent.evaluate_search_results.return_value = [valid]
    search = Mock()
    search.search.return_value = [{"url": valid["url"], "title": valid["link_text"], "snippet": "", "publisher": "disclosure.example"}]
    probe = Mock()
    probe.probe_many.side_effect = lambda values: [
        {**value, "access_status": "reachable", "status": "discovered", "http_status": 200,
         "final_url": value["url"], "error": None}
        for value in values
    ]
    engine = TrustedSourceDiscovery(agent=agent, web_search=search, url_probe=probe)

    qualified, audited, warnings = engine.discover(
        intent=TaskIntent(station_name="三峡电站", target_period="2023", query_hints=("三峡电站 2023 发电量",)),
        station={"entity_id": "station_three_gorges", "canonical_name": "Three Gorges Dam", "local_name": "三峡电站", "aliases": "三峡水电站"},
        gem_candidates=[irrelevant],
    )

    assert warnings == []
    assert all(isinstance(item, CandidateSource) for item in qualified)
    assert [item.url for item in qualified] == [valid["url"]]
    assert any(item.get("status") == "ineligible" and "安全责任" in item.get("error", "") for item in audited)
    assert search.search.call_args.args[0] == (
        "三峡电站 2023 发电量", "三峡工程 2023 年全年发电量", "长江电力 2023 三峡电站 年度报告",
    )


def test_sse_discovery_uses_deterministic_operator_hint_without_deepseek():
    official = _candidate(
        "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-01-08/600900_20250108_8R1Z.pdf",
        "长江电力2024年发电量完成情况公告",
        method="sse_official_disclosure",
    )
    official["metadata"] = {
        "issuer_name": "中国长江电力股份有限公司",
        "security_code": "600900",
    }
    probe = Mock()
    probe.probe_many.side_effect = lambda values: [
        {
            **value,
            "access_status": "requires_browser",
            "status": "discovered",
            "http_status": 200,
            "final_url": value["url"],
            "error": "HTTP 200：PDF 链接返回 HTML，需要浏览器验证",
            "metadata": {**(value.get("metadata") or {}), "document_mismatch": "expected_pdf_received_html"},
        }
        for value in values
    ]
    with patch("hydro_platform.intelligence.sse_disclosure.SseDisclosureProvider") as provider:
        provider.return_value.discover.return_value = [official]
        qualified, audited, warnings = TrustedSourceDiscovery(
            agent=type("NoDeepSeek", (), {"enabled": False})(),
            url_probe=probe,
        ).discover(
            intent=TaskIntent(
                station_name="金沙江白鹤滩水电站",
                target_period="2024",
                metric="generation",
                query_hints=("金沙江白鹤滩水电站 2024 发电量",),
            ),
            station={
                "entity_id": "station_baihetan",
                "canonical_name": "Baihetan hydroelectric plant",
                "local_name": "金沙江白鹤滩水电站",
                "country": "China",
                "operator": "China Yangzi River Three Gorges Group",
                "aliases": [],
            },
            enabled_providers={"sse_disclosure"},
        )

    assert warnings == []
    assert len(qualified) == 1
    assert qualified[0].url == official["url"]
    provider.return_value.discover.assert_called_once_with(
        issuers=[{
            "security_code": "600900",
            "issuer_name": "中国长江电力股份有限公司",
            "issuer_source": "deterministic_operator_alias",
        }],
        target_year="2024",
    )
    assert audited


def test_engine_keeps_relevant_real_search_result_when_model_returns_no_candidate():
    source = {
        "url": "https://news.example/three-gorges-2023.html",
        "title": "三峡电站2023年发电量802.71亿千瓦时",
        "snippet": "三峡电站 2023 年发电量年度报告",
        "publisher": "news.example",
        "query": "三峡电站 2023 发电量",
    }
    agent = Mock()
    agent.search.return_value = []
    agent.evaluate_search_results.return_value = []
    search = Mock()
    search.search.return_value = [source]
    probe = Mock()
    probe.probe_many.side_effect = lambda values: [
        {**value, "access_status": "reachable", "status": "discovered", "http_status": 200,
         "final_url": value["url"], "error": None}
        for value in values
    ]

    qualified, _, _ = TrustedSourceDiscovery(agent=agent, web_search=search, url_probe=probe).discover(
        intent=TaskIntent(station_name="长江三峡水电站", target_period="2023", query_hints=(source["query"],)),
        station={"entity_id": "station_three_gorges", "canonical_name": "Three Gorges Dam hydroelectric plant",
                 "local_name": "长江三峡水电站", "aliases": None},
    )

    assert all(isinstance(item, CandidateSource) for item in qualified)
    assert [item.url for item in qualified] == [source["url"]]
    assert qualified[0].source_type == "reference"
    assert qualified[0].metadata["requires_manual_verification"] is True


def test_engine_resolves_public_attachment_when_entry_page_has_no_generation_value():
    """入口页只是报告索引时，公开附件须作为独立可采集候选重新预检。"""
    entry_url = "https://publisher.example/reports/three-gorges-2024"
    attachment_url = "https://publisher.example/files/three-gorges-2024-generation.pdf"
    agent = Mock()
    agent.search.return_value = []
    agent.evaluate_search_results.return_value = []
    search = Mock()
    search.search.return_value = [{
        "url": entry_url, "title": "Three Gorges report index 2024",
        "snippet": "Report centre", "publisher": "publisher.example", "query": "Three Gorges 2024 annual generation",
    }]
    probe = Mock()

    def probe_values(values):
        rows = []
        for value in values:
            metadata = dict(value.get("metadata") or {})
            if value["url"] == entry_url:
                metadata.update({
                    "content_preview": "Three Gorges report centre 2024.",
                    "discovered_links": [{
                        "url": attachment_url,
                        "text": "Three Gorges Dam 2024 annual generation report PDF",
                    }],
                })
            else:
                metadata["content_preview"] = "Three Gorges Dam 2024 annual generation report."
            rows.append({
                **value, "metadata": metadata, "access_status": "reachable", "status": "discovered",
                "http_status": 200, "final_url": value["url"], "error": None,
            })
        return rows

    probe.probe_many.side_effect = probe_values
    qualified, audited, warnings = TrustedSourceDiscovery(
        agent=agent, web_search=search, url_probe=probe,
    ).discover(
        intent=TaskIntent(station_name="Three Gorges Dam", target_period="2024", query_hints=("Three Gorges 2024 annual generation",)),
        station={"entity_id": "station_attachment", "canonical_name": "Three Gorges Dam", "local_name": None, "aliases": None},
    )

    assert warnings == []
    assert [item.url for item in qualified] == [attachment_url]
    assert qualified[0].discovery_method == "html_attachment_link"
    assert qualified[0].metadata["parent_url"] == entry_url
    assert len(probe.probe_many.call_args_list) == 2
    assert any(item.get("url") == entry_url and item.get("status") == "ineligible" for item in audited)


def test_real_task_discovery_persists_program_search_lead_and_candidate_lineage(db):
    db.execute(
        "INSERT INTO stations(entity_id, entity_type, canonical_name, local_name) VALUES (?, 'station', ?, ?)",
        ("station-lead", "Three Gorges Dam", "三峡电站"),
    )
    db.execute(
        """INSERT INTO tasks(
               task_id, entity_id, entity_type, task_type, target_period,
               status, created_at, updated_at
           ) VALUES (?, ?, 'station', 'station_generation', '2023', 'pending',
                     '2026-09-14T00:00:00Z', '2026-09-14T00:00:00Z')""",
        ("station-lead::station_generation::2023", "station-lead"),
    )
    db.commit()
    source = {
        "url": "https://disclosure.example/three-gorges-2023.pdf",
        "title": "三峡电站2023年年度发电量802.71亿千瓦时",
        "snippet": "三峡电站 2023 年全年发电量年度报告",
        "publisher": "disclosure.example",
        "query": "三峡电站 2023 完成发电量",
        "search_engine": "test-program-search",
    }
    agent = Mock()
    agent.search.return_value = []
    agent.evaluate_search_results.return_value = []
    search = Mock()
    search.search.return_value = [source]
    probe = Mock()
    probe.probe_many.side_effect = lambda values: [
        {**value, "access_status": "reachable", "status": "discovered", "http_status": 200,
         "final_url": value["url"], "error": None}
        for value in values
    ]

    qualified, _, warnings = TrustedSourceDiscovery(
        agent=agent, web_search=search, url_probe=probe, conn=db,
    ).discover(
        task_id="station-lead::station_generation::2023",
        intent=TaskIntent(station_name="三峡电站", target_period="2023", query_hints=(source["query"],)),
        station={"entity_id": "station-lead", "canonical_name": "Three Gorges Dam", "local_name": "三峡电站"},
    )

    assert warnings == []
    assert len(qualified) == 1
    assert qualified[0].task_id == "station-lead::station_generation::2023"
    assert qualified[0].lead_id
    row = db.execute(
        "SELECT provider, query_text, url, status, raw_payload_hash FROM search_leads"
    ).fetchone()
    assert tuple(row) == (
        "test-program-search", source["query"], source["url"], "normalized", row[4],
    )
    assert len(row[4]) == 64


def test_chinese_station_query_prefers_short_name_and_completed_generation_phrase():
    intent = Api._station_search_intent({
        "local_name": "长江三峡水电站",
        "canonical_name": "Three Gorges Dam hydroelectric plant",
    }, "2023")

    assert intent.query_hints[0] == '三峡电站 2023 完成发电量'
