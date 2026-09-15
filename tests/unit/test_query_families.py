from unittest.mock import Mock

from hydro_platform.intelligence.deepseek_agent import TaskIntent
from hydro_platform.intelligence.query_families import QueryFamilyPlanner
from hydro_platform.intelligence.trusted_source_discovery import TrustedSourceDiscovery


def test_query_families_keep_report_and_operator_paths_bounded_without_urls():
    variants = QueryFamilyPlanner.variants(
        station={
            "canonical_name": "Three Gorges Dam",
            "local_name": "三峡电站",
            "operator": "长江电力",
        },
        target_period="2024",
        verified_domains=("www.ctg.com.cn",),
        limit=5,
    )

    assert [item.family for item in variants] == [
        "station_annual_generation",
        "station_full_year_generation",
        "operator_annual_disclosure",
        "verified_site_report_index",
    ]
    assert all("http://" not in item.query and "https://" not in item.query for item in variants)
    assert any("site:ctg.com.cn" in item.query for item in variants)


def test_failure_rewrite_does_not_retry_network_failures():
    intent = TaskIntent(
        station_name="三峡电站", target_period="2024",
        query_hints=("三峡电站 2024 完成发电量",),
    )
    assert QueryFamilyPlanner.rewrite_after_failure(
        intent=intent,
        station={"local_name": "三峡电站"},
        attempted_queries=intent.query_hints,
        failure_code="timeout",
    ) == ()


def test_trusted_discovery_retries_empty_search_once_with_report_query():
    search = Mock()
    search.search.side_effect = [[], [{
        "url": "https://publisher.example/three-gorges-2024.pdf",
        "title": "三峡电站 2024 年度发电量报告",
        "snippet": "三峡电站 2024 年全年发电量报告",
        "publisher": "publisher.example",
        "query": "三峡电站 2024 年度报告 发电量",
    }]]
    search.last_diagnostics = []
    probe = Mock()
    probe.probe_many.side_effect = lambda values: [
        {
            **value,
            "access_status": "reachable",
            "status": "discovered",
            "http_status": 200,
            "final_url": value["url"],
            "error": None,
            "metadata": {"content_preview": "三峡电站 2024 年全年发电量报告"},
        }
        for value in values
    ]
    events = []
    qualified, _, warnings = TrustedSourceDiscovery(
        agent=type("NoAgent", (), {"enabled": False})(),
        web_search=search,
        url_probe=probe,
    ).discover(
        intent=TaskIntent(
            station_name="三峡电站", target_period="2024",
            query_hints=("三峡电站 2024 完成发电量",),
        ),
        station={
            "entity_id": "three-gorges",
            "canonical_name": "Three Gorges Dam",
            "local_name": "三峡电站",
            "country": "China",
        },
        on_event=lambda stage, payload: events.append((stage, payload)),
    )

    assert any("DeepSeek" in item for item in warnings)
    assert len(qualified) == 1
    assert search.search.call_count == 2
    assert any(stage == "program_search_retry" for stage, _ in events)
    retry_queries = search.search.call_args_list[1].args[0]
    assert any("年度报告" in query or "公告" in query for query in retry_queries)


def test_trusted_discovery_retries_when_search_results_are_explicitly_irrelevant_and_keeps_audit():
    search = Mock()
    search.search.side_effect = [
        [{
            "url": "https://publisher.example/safety-notice.html",
            "title": "2024 年水电站安全责任人名单",
            "snippet": "安全生产责任公告",
            "publisher": "publisher.example",
        }],
        [{
            "url": "https://publisher.example/three-gorges-2024.pdf",
            "title": "三峡电站 2024 年度发电量报告",
            "snippet": "三峡电站 2024 年全年发电量报告",
            "publisher": "publisher.example",
        }],
    ]
    search.last_diagnostics = []
    probe = Mock()
    probe.probe_many.side_effect = lambda values: [
        {
            **value,
            "access_status": "reachable",
            "status": "discovered",
            "http_status": 200,
            "final_url": value["url"],
            "error": None,
            "metadata": {"content_preview": value.get("snippet", "")},
        }
        for value in values
    ]
    events = []
    qualified, audited, _ = TrustedSourceDiscovery(
        agent=type("NoAgent", (), {"enabled": False})(),
        web_search=search,
        url_probe=probe,
    ).discover(
        intent=TaskIntent(
            station_name="三峡电站", target_period="2024",
            query_hints=("三峡电站 2024 完成发电量",),
        ),
        station={
            "entity_id": "three-gorges",
            "canonical_name": "Three Gorges Dam",
            "local_name": "三峡电站",
            "country": "China",
        },
        on_event=lambda stage, payload: events.append((stage, payload)),
    )

    assert [item.url for item in qualified] == ["https://publisher.example/three-gorges-2024.pdf"]
    assert any(item.get("url") == "https://publisher.example/safety-notice.html" and item.get("status") == "ineligible" for item in audited)
    retry_events = [payload for stage, payload in events if stage == "program_search_retry"]
    assert len(retry_events) == 1
    assert retry_events[0]["failure_code"] == "irrelevant"
    assert retry_events[0]["preserved_initial_count"] == 1
    assert search.search.call_count == 2
