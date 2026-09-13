"""统一可信来源发现。

候选可来自程序控制的搜索、DeepSeek 原生联网搜索或 GEM 外链，但必须通过
同一套 URL 预检、任务相关性校验和评分。该服务永远不创建采集任务，也不写
入正式来源或事实表。
"""

from __future__ import annotations

from typing import Any, Callable

from ..discovery.relevance import CandidateRelevanceVerifier
from ..discovery.url_probe import UrlProbe
from ..reliability.scorer import ReliabilityScorer
from .deepseek_agent import DeepSeekAgentError, DeepSeekResponsesAgent, TaskIntent
from .web_search import WebSearchError, WebSearchProvider


class TrustedSourceDiscovery:
    """合并多通道检索结果并返回可审阅候选。"""

    def __init__(
        self,
        *,
        agent: DeepSeekResponsesAgent,
        web_search: WebSearchProvider | None = None,
        url_probe: UrlProbe | None = None,
        scorer: ReliabilityScorer | None = None,
        verifier: CandidateRelevanceVerifier | None = None,
    ):
        self.agent = agent
        self.web_search = web_search or WebSearchProvider()
        self.url_probe = url_probe or UrlProbe()
        self.scorer = scorer or ReliabilityScorer()
        self.verifier = verifier or CandidateRelevanceVerifier()

    @staticmethod
    def _deduplicate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            url = str(candidate.get("canonical_url") or candidate.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append({**candidate, "canonical_url": url})
        return merged

    @staticmethod
    def _program_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把实际搜索引擎返回的结果保留为低等级候选。

        DeepSeek 的评估用于提升排序和解释，但模型暂时不可用、或没有选择某个
        搜索结果时，不能让已验证存在的 URL 凭空消失。它们仍须经过 URL 预检和
        电站/年份/指标硬校验，且默认标为 reference，必须由用户核实后才可使用。
        """
        candidates: list[dict[str, Any]] = []
        for source in results:
            url = str(source.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            candidates.append({
                "url": url,
                "canonical_url": url,
                "link_text": str(source.get("title") or url)[:500],
                "section_title": str(source.get("publisher") or "程序联网搜索")[:300],
                "source_type": "reference",
                "document_type": "pdf" if url.lower().split("?", 1)[0].endswith(".pdf") else "html",
                "discovery_method": "program_search_result",
                "match_reason": "程序联网搜索结果；需人工核实发布机构与原始数据",
                "metadata": {
                    "query": str(source.get("query") or ""),
                    "search_title": str(source.get("title") or "")[:500],
                    "search_snippet": str(source.get("snippet") or "")[:1600],
                    "search_provider": str(source.get("search_engine") or "program_controlled_search"),
                    "requires_manual_verification": True,
                },
            })
        return candidates

    def discover(
        self,
        *,
        intent: TaskIntent,
        station: dict[str, Any],
        gem_candidates: list[dict[str, Any]] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """返回 ``(qualified, audited, warnings)``。

        ``audited`` 保留不合格/不可访问候选供台账审计；只有 ``qualified`` 可以
        显示为采集入口。
        """
        warnings: list[str] = []
        all_candidates: list[dict[str, Any]] = []

        def event(stage: str, payload: dict[str, Any]) -> None:
            if on_event:
                on_event(stage, payload)

        # 英文 seedlist 名称与当地报道的简称、运营主体之间常没有一一对应关系。
        # 在实际搜索之前，请 DeepSeek 仅规划两条补充检索词；模型不返回 URL，
        # 也不会削弱下方对电站/年份/年度口径的硬校验。
        planner = getattr(self.agent, "suggest_search_queries", None)
        if callable(planner):
            try:
                event("query_planning", {"base_queries": list(intent.query_hints)})
                suggested = planner(intent=intent, station=station, limit=2)
                if isinstance(suggested, (list, tuple)):
                    # 固定主检索词永远保留在第一位，防止模型的别名建议覆盖
                    # 可重复、可审计的 seedlist 检索路径。
                    merged_hints: list[str] = []
                    for hint in (list(intent.query_hints[:1]) + list(suggested) + list(intent.query_hints[1:])):
                        hint = str(hint or "").strip()
                        if hint and hint not in merged_hints:
                            merged_hints.append(hint)
                    intent = TaskIntent(
                        station_name=intent.station_name,
                        target_period=intent.target_period,
                        metric=intent.metric,
                        source_policy=intent.source_policy,
                        auto_execute=intent.auto_execute,
                        query_hints=tuple(merged_hints[:3]),
                    )
                    event("query_planning_done", {"queries": list(intent.query_hints)})
            except DeepSeekAgentError as exc:
                warnings.append(f"DeepSeek 检索词规划不可用：{exc}")

        # 中国上市运营主体的“发电量完成情况公告”由交易所发布原始 PDF。
        # 这是独立于普通网页搜索的官方通道；模型只给出代码线索，交易所目录
        # 与 PDF 正文才是最终证据。
        if str(station.get("country") or "").strip().lower() == "china":
            issuer_planner = getattr(self.agent, "suggest_listed_issuers", None)
            if callable(issuer_planner):
                try:
                    from .sse_disclosure import SseDisclosureProvider
                    event("official_disclosure_search", {})
                    issuers = issuer_planner(intent=intent, station=station)
                    if isinstance(issuers, list):
                        official = SseDisclosureProvider().discover(issuers=issuers, target_year=intent.target_period)
                        all_candidates.extend(official)
                        event("official_disclosure_search_done", {"count": len(official)})
                except DeepSeekAgentError as exc:
                    warnings.append(f"上市公告主体识别不可用：{exc}")

        # 通道 A：DeepSeek 原生联网搜索。失败不阻断独立搜索通道。
        try:
            event("deepseek_search", {})
            native = self.agent.search(intent=intent, station=station)
            all_candidates.extend(native)
            event("deepseek_search_done", {"count": len(native)})
        except DeepSeekAgentError as exc:
            warnings.append(f"DeepSeek 原生搜索不可用：{exc}")

        # 通道 B：可审计的程序控制搜索，再由 DeepSeek 限定只能从真实结果中选择。
        try:
            event("program_search", {"queries": list(intent.query_hints)})
            results = self.web_search.search(intent.query_hints)
            event("program_search_done", {"count": len(results)})
            # 先保存搜索引擎实际给出的 URL；模型仅能补充审核结论，不能作为
            # 候选存在与否的唯一决定者。
            all_candidates.extend(self._program_candidates(results))
            evaluated = self.agent.evaluate_search_results(intent=intent, station=station, results=results)
            all_candidates.extend(evaluated)
        except (WebSearchError, DeepSeekAgentError) as exc:
            warnings.append(f"程序搜索通道不可用：{exc}")

        # 通道 C：GEM 仅作为补充线索，不再单独形成“官方来源发现”的结果。
        all_candidates.extend(gem_candidates or [])
        merged = self._deduplicate(all_candidates)
        task = {
            "entity_id": station.get("entity_id"), "entity_name": station.get("canonical_name"),
            "target_period": intent.target_period, "metric": intent.metric,
        }
        ranked = self.scorer.rank_sources(merged, task)
        probed = self.url_probe.probe_many(ranked)

        qualified: list[dict[str, Any]] = []
        audited: list[dict[str, Any]] = []
        for candidate in probed:
            if candidate.get("access_status") not in {"reachable", "requires_browser"}:
                audited.append(candidate)
                continue
            relevance = self.verifier.verify(
                candidate, station=station, target_period=intent.target_period, metric=intent.metric,
            )
            enriched = {
                **candidate,
                "relevance_score": relevance.score,
                "relevance_evidence": relevance.evidence,
                "period_scope": relevance.period_scope,
                "match_reason": relevance.reason if relevance.eligible else relevance.reason,
            }
            if not relevance.eligible:
                audited.append({**enriched, "status": "ineligible", "error": relevance.reason})
                continue
            # 相关性经过硬门槛后，才参与最终排序；来源可信度仍参与但不能覆盖硬门槛。
            enriched["combined_score"] = round(
                min(1.0, float(candidate.get("combined_score") or 0.0) * 0.65 + relevance.score * 0.35), 4
            )
            qualified.append(enriched)
            audited.append(enriched)

        qualified.sort(key=lambda item: item.get("combined_score", 0.0), reverse=True)
        return qualified[:10], audited, warnings
