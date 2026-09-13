"""程序控制的搜索必须保留真实结果 URL，而不是让模型编造链接。"""

import pytest

from hydro_platform.intelligence.web_search import WebSearchError, WebSearchProvider


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
