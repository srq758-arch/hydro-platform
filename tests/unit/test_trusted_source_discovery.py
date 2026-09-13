"""统一可信来源发现：多通道融合后必须以任务相关性为硬门槛。"""

from unittest.mock import Mock

from hydro_platform.discovery.relevance import CandidateRelevanceVerifier
from hydro_platform.app.api import Api
from hydro_platform.intelligence.deepseek_agent import TaskIntent
from hydro_platform.intelligence.trusted_source_discovery import TrustedSourceDiscovery


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
    assert [item["url"] for item in qualified] == [valid["url"]]
    assert any(item.get("status") == "ineligible" and "安全责任" in item.get("error", "") for item in audited)
    assert search.search.call_args.args[0] == (
        "三峡电站 2023 发电量", "三峡工程 2023 年全年发电量", "长江电力 2023 三峡电站 年度报告",
    )


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

    assert [item["url"] for item in qualified] == [source["url"]]
    assert qualified[0]["source_type"] == "reference"
    assert qualified[0]["metadata"]["requires_manual_verification"] is True


def test_chinese_station_query_prefers_short_name_and_completed_generation_phrase():
    intent = Api._station_search_intent({
        "local_name": "长江三峡水电站",
        "canonical_name": "Three Gorges Dam hydroelectric plant",
    }, "2023")

    assert intent.query_hints[0] == '三峡电站 2023 完成发电量'
