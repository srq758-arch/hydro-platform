"""程序控制的搜索必须保留真实结果 URL，而不是让模型编造链接。"""

import pytest

from hydro_platform.intelligence.web_search import (
    ProviderPolicy,
    ProviderQuotaLedger,
    SearchRuntime,
    WebSearchError,
    WebSearchProvider,
)


class _Response:
    text = '''<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.gov%2Freport.pdf">Official report</a><a class="result__snippet">2024 generation report</a></div>'''

    def raise_for_status(self):
        return None


class _EmptyResponse:
    text = "<html><body>No results</body></html>"

    def raise_for_status(self):
        return None


class _So360Response:
    text = '''<li class="res-list"><h3 class="res-title"><a data-mdurl="https://disclosure.example/three-gorges-2023.pdf">三峡电站2023年发电量公告</a></h3><p>三峡电站 2023 年发电量</p></li>'''

    def raise_for_status(self):
        return None


class _CaptchaResponse:
    url = "https://qcaptcha.so.com/"
    text = "<html><title>访问异常页面</title></html>"

    def raise_for_status(self):
        return None


class _SogouResponse:
    text = '''<div class="vrwrap"><h3><a>三峡电站2025年全年发电量</a></h3><div class="fz-mid">三峡电站 2025 年全年发电量</div><div data-url="https://publisher.example/three-gorges-2025.html"></div></div>'''

    def raise_for_status(self):
        return None


def test_duckduckgo_result_url_is_unwrapped_and_tagged_with_query(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)
    provider = WebSearchProvider(get=lambda *_args, **_kwargs: _Response())

    results = provider.search(["Example Dam 2024 generation"])

    assert results == [{
        "url": "https://example.gov/report.pdf", "title": "Official report",
        "snippet": "2024 generation report", "publisher": "example.gov",
        "query": "Example Dam 2024 generation",
    }]


def test_empty_duckduckgo_falls_back_to_360_and_uses_publisher_url(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)

    def fake_get(url, **_kwargs):
        return _So360Response() if "so.com" in url else _EmptyResponse()

    results = WebSearchProvider(get=fake_get).search(["三峡电站 2023 发电量"])

    assert results == [{
        "url": "https://disclosure.example/three-gorges-2023.pdf",
        "title": "三峡电站2023年发电量公告",
        "snippet": "三峡电站2023年发电量公告 三峡电站 2023 年发电量",
        "publisher": "disclosure.example",
        "search_engine": "360 搜索",
        "query": "三峡电站 2023 发电量",
    }]


def test_captcha_360_falls_back_to_sogou_real_publisher_url(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)

    def fake_get(url, **_kwargs):
        if "so.com" in url:
            return _CaptchaResponse()
        if "sogou.com" in url:
            return _SogouResponse()
        return _EmptyResponse()

    results = WebSearchProvider(get=fake_get).search(["三峡电站 2025 全年发电量"])

    assert results == [{
        "url": "https://publisher.example/three-gorges-2025.html",
        "title": "三峡电站2025年全年发电量",
        "snippet": "三峡电站 2025 年全年发电量",
        "publisher": "publisher.example",
        "search_engine": "搜狗搜索",
        "query": "三峡电站 2025 全年发电量",
    }]


def test_all_unparseable_engines_raise_search_unavailable_not_empty_result(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)

    def fake_get(url, **_kwargs):
        return _CaptchaResponse() if "so.com" in url else _EmptyResponse()

    with pytest.raises(WebSearchError, match="未获得可解析的网页搜索结果"):
        WebSearchProvider(get=fake_get).search(["三峡电站 2025 年发电量"])


def test_all_program_search_engines_run_and_report_independent_diagnostics(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        if "duckduckgo" in url:
            return _Response()
        if "so.com" in url:
            return _So360Response()
        if "sogou.com" in url:
            return _SogouResponse()
        raise AssertionError(url)

    results, diagnostics = WebSearchProvider(get=fake_get).search_with_diagnostics(
        ["三峡电站 2023 年发电量"]
    )

    assert len(calls) == 3
    assert {item["provider"] for item in diagnostics} == {"DuckDuckGo", "360 搜索", "搜狗搜索"}
    assert all(item["status"] == "ok" for item in diagnostics)
    assert {item["url"] for item in results} == {
        "https://example.gov/report.pdf",
        "https://disclosure.example/three-gorges-2023.pdf",
        "https://publisher.example/three-gorges-2025.html",
    }


def test_provider_budget_is_independent_and_visible_in_diagnostics(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)
    names = ("DuckDuckGo", "360 搜索", "搜狗搜索")
    policies = {name: ProviderPolicy(max_calls=1) for name in names}
    provider = WebSearchProvider(get=lambda *_args, **_kwargs: _Response(), provider_policies=policies)

    results, diagnostics = provider.search_with_diagnostics(["三峡 2024 发电量", "三峡 2023 发电量"])

    assert results
    assert {item["provider"] for item in diagnostics if item["status"] == "budget_exhausted"} == set(names)
    assert all(item["count"] == 0 for item in diagnostics if item["status"] == "budget_exhausted")


def test_provider_circuit_breaker_skips_only_the_failing_provider(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("timeout")))
        if "duckduckgo" in url:
            raise __import__("requests").Timeout("simulated timeout")
        return _So360Response() if "so.com" in url else _EmptyResponse()

    provider = WebSearchProvider(
        get=fake_get,
        provider_policies={"DuckDuckGo": ProviderPolicy(failure_threshold=1)},
    )
    _, diagnostics = provider.search_with_diagnostics(["三峡 2024 发电量", "三峡 2023 发电量"])

    assert sum("duckduckgo" in url for url, _ in calls) == 1
    assert any(item["provider"] == "DuckDuckGo" and item["status"] == "circuit_open" for item in diagnostics)
    assert sum("so.com" in url for url, _ in calls) == 2


def test_provider_policy_timeout_is_forwarded_to_http_fallback(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)
    timeouts = []

    def fake_get(url, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        return _Response()

    provider = WebSearchProvider(
        get=fake_get,
        provider_policies={name: ProviderPolicy(timeout_seconds=4.5) for name in ("DuckDuckGo", "360 搜索", "搜狗搜索")},
    )
    provider.search(["三峡 2024 发电量"])

    assert timeouts and set(timeouts) == {4.5}


def test_shared_provider_quota_is_rate_limited_across_search_calls(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)
    names = ("DuckDuckGo", "360 搜索", "搜狗搜索")
    clock_value = [100.0]
    ledger = ProviderQuotaLedger(clock=lambda: clock_value[0])
    policies = {name: ProviderPolicy(rate_limit_per_minute=1) for name in names}
    provider = WebSearchProvider(
        get=lambda *_args, **_kwargs: _Response(),
        provider_policies=policies,
        quota_ledger=ledger,
    )

    provider.search(["三峡 2024 发电量"])
    with pytest.raises(WebSearchError):
        provider.search(["三峡 2023 发电量"])

    assert {item["provider"] for item in provider.last_diagnostics if item["status"] == "rate_limited"} == set(names)
    assert all(
        values.get("rate_limited") == 1
        for values in provider.last_metrics["providers"].values()
    )

    clock_value[0] += 61
    provider.search(["三峡 2022 发电量"])
    assert all(values["calls"] == 1 for values in provider.last_metrics["providers"].values())


def test_provider_cost_metrics_are_recorded_without_response_content(monkeypatch):
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)
    policies = {
        "DuckDuckGo": ProviderPolicy(estimated_cost_per_call=0.2),
        "360 搜索": ProviderPolicy(estimated_cost_per_call=0.5),
        "搜狗搜索": ProviderPolicy(estimated_cost_per_call=1.0),
    }
    provider = WebSearchProvider(
        get=lambda *_args, **_kwargs: _Response(),
        provider_policies=policies,
    )

    provider.search(["三峡 2024 发电量"])

    assert provider.last_metrics["estimated_cost"] == 1.7
    assert set(provider.last_metrics["providers"]) == set(policies)
    assert all(values["calls"] == 1 for values in provider.last_metrics["providers"].values())


def test_search_runtime_shares_quota_between_task_providers(monkeypatch):
    """后台并发任务使用同一运行时后，限流不会按任务实例重置。"""
    monkeypatch.setattr("hydro_platform.intelligence.web_search.GoogleSearchConfig.is_configured", lambda: False)
    names = ("DuckDuckGo", "360 搜索", "搜狗搜索")
    clock_value = [200.0]
    policies = {name: ProviderPolicy(rate_limit_per_minute=1) for name in names}
    runtime = SearchRuntime(
        get=lambda *_args, **_kwargs: _Response(),
        provider_policies=policies,
        quota_ledger=ProviderQuotaLedger(clock=lambda: clock_value[0]),
    )
    first_task_provider = runtime.web_search
    second_task_provider = WebSearchProvider(
        get=lambda *_args, **_kwargs: _Response(),
        provider_policies=policies,
        quota_ledger=runtime.quota_ledger,
    )

    first_task_provider.search(["三峡 2024 发电量"])
    with pytest.raises(WebSearchError):
        second_task_provider.search(["三峡 2024 发电量"])

    snapshot = runtime.snapshot()
    assert all(snapshot[name]["calls"] == 1 for name in names)
    assert {item["provider"] for item in second_task_provider.last_diagnostics if item["status"] == "rate_limited"} == set(names)
