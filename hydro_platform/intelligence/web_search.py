"""程序控制的联网搜索。

DeepSeek 只生成检索意图和评估结果；真正的网页检索由这里执行并返回可审计 URL。
优先使用已配置的 Google Custom Search。没有 Google 凭据时，依次尝试
DuckDuckGo、360 和搜狗搜索；后两者是中文电站名称的重要回退通道。
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import threading
import time
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from ..discovery.google_search import GoogleSearchConfig, GoogleSearchDiscovery


class WebSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderPolicy:
    """单个搜索 Provider 在一次 Discovery 请求中的资源边界。"""

    max_calls: int = 3
    timeout_seconds: float = 15.0
    failure_threshold: int = 3
    rate_limit_per_minute: int | None = None
    estimated_cost_per_call: float = 0.0

    def __post_init__(self) -> None:
        if self.max_calls < 1:
            raise ValueError("max_calls 必须大于 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold 必须大于 0")
        if self.rate_limit_per_minute is not None and self.rate_limit_per_minute < 1:
            raise ValueError("rate_limit_per_minute 必须大于 0")
        if self.estimated_cost_per_call < 0:
            raise ValueError("estimated_cost_per_call 不能小于 0")


class ProviderQuotaLedger:
    """可由多个任务共享的短窗口 Provider 配额与调用统计账本。

    默认 WebSearchProvider 会创建自己的账本；调度器若要跨任务限流，可将同一
    实例注入多个 provider。账本只保存时间戳和计数，不保存 URL、密钥或响应正文。
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._events: dict[str, deque[float]] = {}
        self._stats: dict[str, dict[str, float | int]] = {}

    def try_acquire(self, provider: str, limit_per_minute: int | None) -> bool:
        if limit_per_minute is None:
            return True
        with self._lock:
            now = self._clock()
            window = self._events.setdefault(provider, deque())
            while window and now - window[0] >= 60.0:
                window.popleft()
            if len(window) >= limit_per_minute:
                return False
            window.append(now)
            return True

    def record(self, provider: str, outcome: str, *, estimated_cost: float) -> None:
        with self._lock:
            stats = self._stats.setdefault(provider, {
                "calls": 0, "successes": 0, "empty": 0,
                "failures": 0, "estimated_cost": 0.0,
            })
            stats["calls"] = int(stats["calls"]) + 1
            if outcome == "ok":
                stats["successes"] = int(stats["successes"]) + 1
            elif outcome == "empty":
                stats["empty"] = int(stats["empty"]) + 1
            elif outcome == "failed":
                stats["failures"] = int(stats["failures"]) + 1
            stats["estimated_cost"] = float(stats["estimated_cost"]) + float(estimated_cost)

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {provider: dict(values) for provider, values in self._stats.items()}


class WebSearchProvider:
    """对外部搜索引擎的窄接口；每任务至多三条查询、每条五个结果。"""

    _DEFAULT_POLICY = ProviderPolicy()

    def __init__(
        self,
        *,
        get: Callable[..., Any] = requests.get,
        provider_policies: dict[str, ProviderPolicy] | None = None,
        quota_ledger: ProviderQuotaLedger | None = None,
    ):
        self._get = get
        self.last_diagnostics: list[dict[str, str | int]] = []
        self.last_metrics: dict[str, Any] = {}
        self._provider_policies = dict(provider_policies or {})
        self._quota_ledger = quota_ledger or ProviderQuotaLedger()

    def _policy(self, provider_name: str) -> ProviderPolicy:
        policy = self._provider_policies.get(provider_name)
        if policy is None:
            return self._DEFAULT_POLICY
        if isinstance(policy, ProviderPolicy):
            return policy
        raise TypeError(f"{provider_name} 的 provider policy 必须是 ProviderPolicy")

    def search(self, queries: Iterable[str], *, per_query: int = 5) -> list[dict[str, str]]:
        """兼容入口：只返回结果；需要诊断的调用方使用 ``search_with_diagnostics``。"""
        results, diagnostics = self.search_with_diagnostics(queries, per_query=per_query)
        self.last_diagnostics = diagnostics
        # 旧 API 不新增内部诊断字段，避免既有前端/调用方因多出字段改变行为。
        return [
            {key: value for key, value in item.items() if key != "_provider_label"}
            for item in results
        ]

    def search_with_diagnostics(
        self,
        queries: Iterable[str],
        *,
        per_query: int = 5,
    ) -> tuple[list[dict[str, str]], list[dict[str, str | int]]]:
        """运行所有可用搜索引擎，保留独立 provider 诊断。

        单个引擎有结果绝不能阻断其他引擎；不同索引的覆盖面不同，特别是
        中文公告、交易所附件和运营商站内页面。网络调用仍受三条查询、每引擎
        五条结果的预算约束。
        """
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        attempted = 0
        failures: list[str] = []
        diagnostics: list[dict[str, str | int]] = []
        calls_by_provider: dict[str, int] = {}
        failures_by_provider: dict[str, int] = {}
        request_metrics: dict[str, dict[str, float | int]] = {}

        def finish_metrics() -> None:
            shared = self._quota_ledger.snapshot()
            providers: dict[str, dict[str, float | int]] = {}
            for provider, values in request_metrics.items():
                providers[provider] = dict(values)
            self.last_metrics = {
                "providers": providers,
                "estimated_cost": round(sum(
                    float(values.get("estimated_cost", 0.0)) for values in providers.values()
                ), 8),
                "shared_ledger": shared,
            }

        def record_call(provider: str, outcome: str, policy: ProviderPolicy) -> None:
            current = request_metrics.setdefault(provider, {
                "calls": 0, "successes": 0, "empty": 0,
                "failures": 0, "estimated_cost": 0.0,
            })
            current["calls"] = int(current["calls"]) + 1
            if outcome == "ok":
                current["successes"] = int(current["successes"]) + 1
            elif outcome == "empty":
                current["empty"] = int(current["empty"]) + 1
            elif outcome == "failed":
                current["failures"] = int(current["failures"]) + 1
            current["estimated_cost"] = float(current["estimated_cost"]) + policy.estimated_cost_per_call
            self._quota_ledger.record(provider, outcome, estimated_cost=policy.estimated_cost_per_call)

        for query in list(queries)[:3]:
            query = (query or "").strip()
            if not query:
                continue
            attempted += 1
            engines: list[tuple[str, Callable[[str, int], list[dict[str, str]]]]] = []
            if GoogleSearchConfig.is_configured():
                engines.append(("Google Custom Search", self._google))
            engines.extend([
                ("DuckDuckGo", self._duckduckgo),
                ("360 搜索", self._so360),
                ("搜狗搜索", self._sogou),
            ])
            for provider_name, engine in engines:
                policy = self._policy(provider_name)
                used = calls_by_provider.get(provider_name, 0)
                if used >= policy.max_calls:
                    diagnostics.append({
                        "provider": provider_name, "query": query,
                        "status": "budget_exhausted", "count": 0,
                        "error": f"本次请求已达到 {policy.max_calls} 次调用预算",
                    })
                    continue
                failed = failures_by_provider.get(provider_name, 0)
                if failed >= policy.failure_threshold:
                    diagnostics.append({
                        "provider": provider_name, "query": query,
                        "status": "circuit_open", "count": 0,
                        "error": f"连续失败达到 {policy.failure_threshold} 次，暂时熔断",
                    })
                    continue
                if not self._quota_ledger.try_acquire(provider_name, policy.rate_limit_per_minute):
                    diagnostics.append({
                        "provider": provider_name, "query": query,
                        "status": "rate_limited", "count": 0,
                        "error": f"每分钟调用预算为 {policy.rate_limit_per_minute}",
                    })
                    values = request_metrics.setdefault(provider_name, {
                        "calls": 0, "successes": 0, "empty": 0,
                        "failures": 0, "rate_limited": 0,
                        "estimated_cost": 0.0,
                    })
                    values["rate_limited"] = int(values.get("rate_limited", 0)) + 1
                    continue
                calls_by_provider[provider_name] = used + 1
                try:
                    items = engine(query, per_query, timeout=policy.timeout_seconds)
                except WebSearchError as exc:
                    error = str(exc)
                    failures.append(f"{provider_name}: {error}")
                    failures_by_provider[provider_name] = failed + 1
                    record_call(provider_name, "failed", policy)
                    diagnostics.append({
                        "provider": provider_name, "query": query,
                        "status": "failed", "count": 0, "error": error,
                    })
                    continue
                record_call(provider_name, "ok" if items else "empty", policy)
                diagnostics.append({
                    "provider": provider_name, "query": query,
                    "status": "ok" if items else "empty", "count": len(items), "error": "",
                })
                for item in items:
                    url = item.get("url", "")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    results.append(item | {
                        "query": query,
                        "_provider_label": provider_name,
                    })
        if not results and attempted:
            self.last_diagnostics = diagnostics
            finish_metrics()
            detail = "；".join(dict.fromkeys(failures)) if failures else "搜索页返回了验证码、限流页或不可解析的空结果"
            raise WebSearchError(
                f"未获得可解析的网页搜索结果（已尝试 {attempted} 条检索词）：{detail}。"
                "可稍后重试，或在设置中配置 Google Custom Search 凭据以获得稳定结果。"
            )
        self.last_diagnostics = diagnostics
        finish_metrics()
        return results[:12], diagnostics

    def _google(self, query: str, limit: int, *, timeout: float | None = None) -> list[dict[str, str]]:
        api_key, engine_id = GoogleSearchConfig.from_env()
        raw = GoogleSearchDiscovery(api_key, engine_id)._call_google_api(
            query, min(limit, 10), timeout=timeout,
        )
        return [{"url": item.get("link", ""), "title": item.get("title", ""), "snippet": item.get("snippet", ""),
                 "publisher": item.get("displayLink", "Google 搜索")} for item in raw]

    def _duckduckgo(self, query: str, limit: int, *, timeout: float | None = None) -> list[dict[str, str]]:
        try:
            response = self._get(
                "https://html.duckduckgo.com/html/", params={"q": query}, timeout=timeout or self._DEFAULT_POLICY.timeout_seconds,
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

    def _so360(self, query: str, limit: int, *, timeout: float | None = None) -> list[dict[str, str]]:
        """以 360 搜索作为中文查询的无密钥回退。

        ``data-mdurl`` 是结果页中搜索引擎提供的实际目标 URL；优先使用它，
        因此台账和后续可访问性检查面对的是来源本身，而不是搜索跳转页。
        """
        try:
            response = self._get(
                "https://www.so.com/s", params={"q": query}, timeout=timeout or self._DEFAULT_POLICY.timeout_seconds,
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

    def _sogou(self, query: str, limit: int, *, timeout: float | None = None) -> list[dict[str, str]]:
        """搜狗中文回退，仅读取页面公开提供的真实发布者 URL。"""
        try:
            response = self._get(
                "https://www.sogou.com/web", params={"query": query}, timeout=timeout or self._DEFAULT_POLICY.timeout_seconds,
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


class SearchRuntime:
    """一个后台生命周期内共享的搜索运行时。

    调度器可能同时执行多个任务。每个任务各自 new ``WebSearchProvider`` 会把
    速率窗口、调用统计和预计成本拆散，导致限流只在单任务内生效。调度器/桌面
    应用应创建一个 ``SearchRuntime``，再把它注入各个 API/任务执行器；测试或
    一次性调用仍可继续直接使用 ``WebSearchProvider``。
    """

    def __init__(
        self,
        *,
        get: Callable[..., Any] = requests.get,
        provider_policies: dict[str, ProviderPolicy] | None = None,
        quota_ledger: ProviderQuotaLedger | None = None,
    ) -> None:
        self.quota_ledger = quota_ledger or ProviderQuotaLedger()
        self.web_search = WebSearchProvider(
            get=get,
            provider_policies=provider_policies,
            quota_ledger=self.quota_ledger,
        )

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        """返回不含 URL/正文/密钥的跨任务统计快照。"""
        return self.quota_ledger.snapshot()
