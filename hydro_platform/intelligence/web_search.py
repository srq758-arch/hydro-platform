"""程序控制的联网搜索。

DeepSeek 只生成检索意图和评估结果；真正的网页检索由这里执行并返回可审计 URL。
优先使用已配置的 Google Custom Search。没有 Google 凭据时，依次尝试
DuckDuckGo、360 和搜狗搜索；后两者是中文电站名称的重要回退通道。
"""

from __future__ import annotations

from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from ..discovery.google_search import GoogleSearchConfig, GoogleSearchDiscovery


class WebSearchError(RuntimeError):
    pass


class WebSearchProvider:
    """对外部搜索引擎的窄接口；每任务至多三条查询、每条五个结果。"""

    def __init__(self, *, get: Callable[..., Any] = requests.get):
        self._get = get

    def search(self, queries: Iterable[str], *, per_query: int = 5) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        attempted = 0
        failures: list[str] = []
        for query in list(queries)[:3]:
            query = (query or "").strip()
            if not query:
                continue
            attempted += 1
            if GoogleSearchConfig.is_configured():
                try:
                    items = self._google(query, per_query)
                except WebSearchError as exc:
                    failures.append(str(exc))
                    items = []
            else:
                # 某一个无密钥引擎出现验证码、限流或连接错误，不代表没有网页
                # 结果；必须继续尝试其余引擎。只有所有通道都未解析到结果时，
                # 才向上层明确报告“搜索不可用”，绝不伪装成“没有可信来源”。
                items = []
                for engine in (self._duckduckgo, self._so360, self._sogou):
                    try:
                        items = engine(query, per_query)
                    except WebSearchError as exc:
                        failures.append(str(exc))
                        continue
                    if items:
                        break
            for item in items:
                url = item.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(item | {"query": query})
        if not results and attempted:
            detail = "；".join(dict.fromkeys(failures)) if failures else "搜索页返回了验证码、限流页或不可解析的空结果"
            raise WebSearchError(
                f"未获得可解析的网页搜索结果（已尝试 {attempted} 条检索词）：{detail}。"
                "可稍后重试，或在设置中配置 Google Custom Search 凭据以获得稳定结果。"
            )
        return results[:12]

    def _google(self, query: str, limit: int) -> list[dict[str, str]]:
        api_key, engine_id = GoogleSearchConfig.from_env()
        raw = GoogleSearchDiscovery(api_key, engine_id)._call_google_api(query, min(limit, 10))
        return [{"url": item.get("link", ""), "title": item.get("title", ""), "snippet": item.get("snippet", ""),
                 "publisher": item.get("displayLink", "Google 搜索")} for item in raw]

    def _duckduckgo(self, query: str, limit: int) -> list[dict[str, str]]:
        try:
            response = self._get(
                "https://html.duckduckgo.com/html/", params={"q": query}, timeout=15,
                headers={"User-Agent": "Mozilla/5.0 HydroPlatform/1.0 source-discovery"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WebSearchError(f"搜索服务不可用：{exc.__class__.__name__}") from exc
        soup = BeautifulSoup(response.text, "html.parser")
        items: list[dict[str, str]] = []
        for link in soup.select(".result__a"):
            href = self._unwrap_duckduckgo_url(link.get("href", ""))
            if not href.startswith(("http://", "https://")):
                continue
            container = link.find_parent(class_="result")
            snippet = container.select_one(".result__snippet") if container else None
            items.append({"url": href, "title": link.get_text(" ", strip=True),
                          "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                          "publisher": urlparse(href).netloc})
            if len(items) >= limit:
                break
        return items

    def _so360(self, query: str, limit: int) -> list[dict[str, str]]:
        """以 360 搜索作为中文查询的无密钥回退。

        ``data-mdurl`` 是结果页中搜索引擎提供的实际目标 URL；优先使用它，
        因此台账和后续可访问性检查面对的是来源本身，而不是搜索跳转页。
        """
        try:
            response = self._get(
                "https://www.so.com/s", params={"q": query}, timeout=15,
                headers={"User-Agent": "Mozilla/5.0 HydroPlatform/1.0 source-discovery"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WebSearchError(f"搜索服务不可用：{exc.__class__.__name__}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        # 360 在连续自动查询时会返回 HTTP 200 的验证码页；它不是“无结果”。
        if "qcaptcha.so.com" in str(getattr(response, "url", "")) or "访问异常" in soup.get_text(" ", strip=True)[:200]:
            return []
        items: list[dict[str, str]] = []
        for link in soup.select("h3.res-title a"):
            # ``data-mdurl`` is the publisher URL, while href is an opaque
            # redirect URL owned by the search engine.
            url = str(link.get("data-mdurl") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            container = link.find_parent("li", class_="res-list")
            snippet = container.get_text(" ", strip=True) if container else ""
            items.append({
                "url": url,
                "title": link.get_text(" ", strip=True),
                "snippet": snippet[:1600],
                "publisher": urlparse(url).netloc,
                "search_engine": "360 搜索",
            })
            if len(items) >= limit:
                break
        return items

    def _sogou(self, query: str, limit: int) -> list[dict[str, str]]:
        """搜狗中文回退，仅读取页面公开提供的真实发布者 URL。"""
        try:
            response = self._get(
                "https://www.sogou.com/web", params={"query": query}, timeout=15,
                headers={"User-Agent": "Mozilla/5.0 HydroPlatform/1.0 source-discovery"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WebSearchError(f"搜索服务不可用：{exc.__class__.__name__}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        items: list[dict[str, str]] = []
        for wrapper in soup.select("div.vrwrap"):
            title = wrapper.select_one("h3 a")
            destination = wrapper.select_one("[data-url]")
            url = str(destination.get("data-url") or "").strip() if destination else ""
            if not title or not url.startswith(("http://", "https://")):
                continue
            snippet_node = wrapper.select_one(".fz-mid")
            items.append({
                "url": url,
                "title": title.get_text(" ", strip=True),
                "snippet": snippet_node.get_text(" ", strip=True)[:1600] if snippet_node else "",
                "publisher": urlparse(url).netloc,
                "search_engine": "搜狗搜索",
            })
            if len(items) >= limit:
                break
        return items

    @staticmethod
    def _unwrap_duckduckgo_url(value: str) -> str:
        if value.startswith("//"):
            value = "https:" + value
        parsed = urlparse(value)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            return unquote(parse_qs(parsed.query).get("uddg", [""])[0])
        return value
