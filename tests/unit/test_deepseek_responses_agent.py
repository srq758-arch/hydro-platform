"""DeepSeek 智能任务代理必须使用 Responses API，并把结果约束为结构化候选。"""

import json

from hydro_platform.intelligence.deepseek_agent import DeepSeekResponsesAgent, TaskIntent


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_agent_plans_and_searches_via_responses_web_search():
    calls = []
    replies = iter([
        {"output_text": json.dumps({
            "station_name": "乌东德水电站", "target_period": "2024", "metric": "generation",
            "source_policy": "official_or_authority", "auto_execute": False,
            "query_hints": ["乌东德 2024 发电量 年报"],
        })},
        {"output_text": json.dumps({"candidates": [{
            "url": "https://www.ctg.com.cn/reports/wudongde-2024.pdf", "title": "2024 年报告",
            "publisher": "中国三峡集团", "document_type": "pdf", "source_type": "official",
            "reason": "搜索结果中的集团报告",
        }]})},
    ])

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return _Response(next(replies))

    agent = DeepSeekResponsesAgent(api_key="test-key", model="deepseek-v4-flash", post=post)
    intent = agent.plan("收集乌东德水电站 2024 年发电量")
    candidates = agent.search(intent=intent, station={"canonical_name": "Wudongde hydroelectric plant", "country": "China"})

    assert intent.station_name == "乌东德水电站"
    assert candidates[0]["discovery_method"] == "deepseek_responses_web_search"
    assert candidates[0]["source_type"] == "official"
    assert calls[0][0].endswith("/responses")
    assert "tools" not in calls[0][1]
    assert calls[1][1]["tools"] == [{"type": "web_search"}]
    assert calls[1][1]["tool_choice"] == {"type": "web_search"}
    assert calls[1][1]["text"] == {"format": {"type": "json_object"}}


def test_intent_normalizes_a_natural_language_year():
    from hydro_platform.intelligence.deepseek_agent import TaskIntent

    intent = TaskIntent.from_dict({"station_name": "示例电站", "target_period": "2024年", "metric": "generation"})

    assert intent.target_period == "2024"


def test_agent_cannot_return_a_url_that_was_not_in_program_search_results():
    def post(_url, **_kwargs):
        return _Response({"output_text": json.dumps({"candidates": [
            {"url": "https://example.gov/real.pdf", "source_type": "authority", "reason": "匹配"},
            {"url": "https://invented.example/fake.pdf", "source_type": "official", "reason": "不应保留"},
        ]})})

    agent = DeepSeekResponsesAgent(api_key="test-key", model="deepseek-v4-flash", post=post)
    intent = TaskIntent(station_name="Example Dam", target_period="2024")
    candidates = agent.evaluate_search_results(
        intent=intent, station={"canonical_name": "Example Dam"},
        results=[{"url": "https://example.gov/real.pdf", "title": "真实报告", "publisher": "Example government", "snippet": "2024"}],
    )

    assert [item["url"] for item in candidates] == ["https://example.gov/real.pdf"]


def test_agent_query_planner_returns_only_short_non_url_hints():
    def post(_url, **_kwargs):
        return _Response({"output_text": json.dumps({"query_hints": [
            "三峡工程 2024 年全年发电量",
            "https://must-not-be-a-search-hint.example/report",
            "中国长江电力 2024 年年度报告 三峡电站",
        ]})})

    agent = DeepSeekResponsesAgent(api_key="test-key", model="deepseek-v4-flash", post=post)
    hints = agent.suggest_search_queries(
        intent=TaskIntent(station_name="长江三峡水电站", target_period="2024"),
        station={"canonical_name": "Three Gorges Dam hydroelectric plant", "local_name": "长江三峡水电站"},
    )

    assert hints == ("三峡工程 2024 年全年发电量", "中国长江电力 2024 年年度报告 三峡电站")
