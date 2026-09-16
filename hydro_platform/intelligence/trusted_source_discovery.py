"""统一可信来源发现。

候选可来自程序控制的搜索、DeepSeek 原生联网搜索或 GEM 外链，但必须通过
同一套 URL 预检、任务相关性校验和评分。该服务永远不创建采集任务，也不写
入正式来源或事实表。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from ..common.enums import SearchLeadStatus
from ..discovery.evidence_document_resolver import EvidenceDocumentResolver
from ..discovery.relevance import CandidateRelevanceVerifier
from ..discovery.search_lead_ledger import SearchLeadLedger
from ..discovery.url_probe import UrlProbe
from ..reliability.scorer import ReliabilityScorer
from ..models.source_pipeline import CandidateSource
from ..pipeline.source_attempt_ledger import SourceAttemptLedger
from ..pipeline.source_contract_adapter import normalize_candidate_sources
from .deepseek_agent import DeepSeekAgentError, DeepSeekResponsesAgent, TaskIntent
from .query_families import QueryFamilyPlanner
from .search_aggregator import SearchAggregator
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
        document_resolver: EvidenceDocumentResolver | None = None,
        conn: sqlite3.Connection | None = None,
    ):
        self.agent = agent
        self.web_search = web_search or WebSearchProvider()
        self.url_probe = url_probe or UrlProbe()
        self.scorer = scorer or ReliabilityScorer()
        self.verifier = verifier or CandidateRelevanceVerifier()
        self.document_resolver = document_resolver or EvidenceDocumentResolver()
        self.conn = conn

    @classmethod
    def canonicalize_url(cls, value: str) -> str:
        """兼容旧调用名；规范化唯一实现位于 SearchAggregator。"""
        return SearchAggregator.canonicalize_url(value)

    @classmethod
    def _deduplicate(cls, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return SearchAggregator.merge(candidates)

    @staticmethod
    def _program_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把实际搜索引擎返回的结果保留为低等级候选。

        DeepSeek 的评估用于提升排序和解释，但模型暂时不可用、或没有选择某个
        搜索结果时，不能让已验证存在的 URL 凭空消失。它们仍须经过 URL 预检和
        电站/年份/指标硬校验，且默认标为 reference，必须由用户核实后才可使用。
        """
        candidates: list[dict[str, Any]] = []
        for rank, source in enumerate(results, start=1):
            url = str(source.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            canonical_url = SearchAggregator.canonicalize_url(url)
            candidates.append({
                "url": url,
                "canonical_url": canonical_url,
                "link_text": str(source.get("title") or url)[:500],
                "section_title": str(source.get("publisher") or SearchAggregator.publisher_domain(canonical_url) or "程序联网搜索")[:300],
                "source_type": "reference",
                "document_type": "pdf" if url.lower().split("?", 1)[0].endswith(".pdf") else "html",
                "discovery_method": "program_search_result",
                "match_reason": "程序联网搜索结果；需人工核实发布机构与原始数据",
                "metadata": {
                    "query": str(source.get("query") or ""),
                    "search_title": str(source.get("title") or "")[:500],
                    "search_snippet": str(source.get("snippet") or "")[:1600],
                    "search_provider": str(source.get("search_engine") or "program_controlled_search"),
                    "rank": rank,
                    "publisher_domain": SearchAggregator.publisher_domain(canonical_url),
                    "discovery_depth": 0,
                    "requires_manual_verification": True,
                    "verify_pdf_text": canonical_url.lower().split("?", 1)[0].endswith(".pdf"),
                },
            })
        return candidates

    def discover(
        self,
        *,
        intent: TaskIntent,
        station: dict[str, Any],
        gem_candidates: list[dict[str, Any]] | None = None,
        supplemental_candidates: list[dict[str, Any]] | None = None,
        task_id: str | None = None,
        enabled_providers: set[str] | frozenset[str] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> tuple[list[CandidateSource], list[dict[str, Any]], list[str]]:
        """返回 ``(qualified, audited, warnings)``。

        ``audited`` 保留不合格/不可访问候选供台账审计；只有 ``qualified`` 可以
        显示为采集入口。
        """
        warnings: list[str] = []
        all_candidates: list[dict[str, Any]] = []
        providers = set(enabled_providers or {
            "sse_disclosure", "deepseek_native_web_search",
            "program_controlled_search", "gem_external_link",
        })
        lead_by_url: dict[str, str] = {}
        ledger: SearchLeadLedger | None = None
        if self.conn is not None and task_id and SearchLeadLedger.is_available(self.conn):
            # search_leads.task_id 有 FK。只有真实已落库任务才能留痕，规划页
            # 仍走 source_discoveries，不能伪造尚未确认的采集任务。
            exists = self.conn.execute(
                "SELECT 1 FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if exists:
                ledger = SearchLeadLedger(self.conn)

        def record_leads(provider: str, values: list[dict[str, Any]], query: str = "") -> None:
            if ledger is None or not values:
                return
            recorded = ledger.record_results(
                task_id=task_id,
                provider=provider,
                default_query=query or (intent.query_hints[0] if intent.query_hints else "provider search"),
                results=values,
            )
            for url, lead_id in recorded.items():
                lead_by_url.setdefault(self.canonicalize_url(url), lead_id)

        def with_lead(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
            annotated: list[dict[str, Any]] = []
            for value in values:
                url = str(value.get("canonical_url") or value.get("final_url") or value.get("url") or "")
                lead_id = lead_by_url.get(self.canonicalize_url(url))
                annotated.append({**value, **({"lead_id": lead_id} if lead_id else {})})
            return annotated

        def event(stage: str, payload: dict[str, Any]) -> None:
            if on_event:
                on_event(stage, payload)

        # WebSearchProvider 的兼容 ``search`` 入口会在每次调用后更新
        # ``last_diagnostics``/``last_metrics``。当首轮结果明显无关时，程序会
        # 有界地补查一轮；如果直接读取最后一次状态，首轮真实查询就会从审计中
        # 消失。这里按调用顺序累积诊断，并在完成事件中合并两轮指标。
        search_diagnostics: list[dict[str, Any]] = []
        search_metric_attempts: list[dict[str, Any]] = []

        def run_program_search(queries: tuple[str, ...]) -> list[dict[str, Any]]:
            try:
                return self.web_search.search(queries)
            finally:
                raw_diagnostics = getattr(self.web_search, "last_diagnostics", [])
                if isinstance(raw_diagnostics, list):
                    search_diagnostics.extend(
                        dict(item) for item in raw_diagnostics if isinstance(item, dict)
                    )
                raw_metrics = getattr(self.web_search, "last_metrics", {})
                if isinstance(raw_metrics, dict) and raw_metrics:
                    search_metric_attempts.append(dict(raw_metrics))

        def merged_search_metrics() -> dict[str, Any]:
            if not search_metric_attempts:
                return {}
            merged: dict[str, Any] = {"providers": {}, "estimated_cost": 0.0}
            for attempt in search_metric_attempts:
                providers = attempt.get("providers")
                if isinstance(providers, dict):
                    for provider, values in providers.items():
                        if not isinstance(values, dict):
                            continue
                        target = merged["providers"].setdefault(provider, {})
                        for key, value in values.items():
                            if key == "estimated_cost":
                                target[key] = float(target.get(key, 0.0)) + float(value or 0.0)
                            elif isinstance(value, (int, float)):
                                target[key] = int(target.get(key, 0)) + int(value)
                            else:
                                target[key] = value
                merged["estimated_cost"] += float(attempt.get("estimated_cost") or 0.0)
            # shared_ledger 是跨任务累计快照，不能相加；以最后一轮为准。
            last_shared = search_metric_attempts[-1].get("shared_ledger")
            if isinstance(last_shared, dict):
                merged["shared_ledger"] = last_shared
            return merged

        def program_search_with_bounded_retry() -> list[dict[str, Any]]:
            """搜索为空/明显无关时只按规则补查一次。

            失败改写只扩大“查询表达”，不生成 URL；网络异常（如 DNS、TLS、
            超时或明确限流）不会继续轰击同一搜索服务。首次查询保持原有顺序，
            保证历史调用、审计和缓存仍可复现。
            """
            attempted = tuple(intent.query_hints)
            try:
                initial = run_program_search(attempted)
            except WebSearchError as exc:
                diagnostics = getattr(self.web_search, "last_diagnostics", [])
                has_provider_failure = any(
                    isinstance(item, dict) and item.get("status") == "failed"
                    for item in diagnostics if isinstance(diagnostics, list)
                )
                failure_code = "provider_failure" if has_provider_failure else "empty_results"
                retry = QueryFamilyPlanner.rewrite_after_failure(
                    intent=intent, station=station, attempted_queries=attempted,
                    failure_code=failure_code,
                    verified_domains=station.get("official_domains") or (),
                )
                if not retry:
                    raise
                retry_queries = tuple(item.query for item in retry)
                event("program_search_retry", {
                    "failure_code": failure_code,
                    "queries": list(retry_queries),
                    "families": [item.family for item in retry],
                })
                return run_program_search(retry_queries)
            if initial:
                # 搜索结果标题/摘要已经明确全部不命中目标实体、年份或指标时，
                # 立即使用第二查询族；原始结果仍保留，后续会进入 audited 审计项。
                raw_candidates = self._program_candidates(initial)
                raw_relevance = [
                    self.verifier.verify(
                        candidate, station=station,
                        target_period=intent.target_period, metric=intent.metric,
                        period_type=intent.period_type,
                    )
                    for candidate in raw_candidates
                ]
                if not raw_relevance or any(item.eligible for item in raw_relevance):
                    return initial
                failure_code = "irrelevant"
                retry = QueryFamilyPlanner.rewrite_after_failure(
                    intent=intent, station=station, attempted_queries=attempted,
                    failure_code=failure_code,
                    verified_domains=station.get("official_domains") or (),
                )
                if not retry:
                    return initial
                retry_queries = tuple(item.query for item in retry)
                event("program_search_retry", {
                    "failure_code": failure_code,
                    "queries": list(retry_queries),
                    "families": [item.family for item in retry],
                    "preserved_initial_count": len(initial),
                })
                # 不丢弃首轮结果：第二轮只是补充召回，首轮无关网页仍会在
                # audited 中显示其排除原因，便于用户判断搜索质量。
                return list(initial) + list(run_program_search(retry_queries))
            retry = QueryFamilyPlanner.rewrite_after_failure(
                intent=intent, station=station, attempted_queries=attempted,
                failure_code="empty_results",
                verified_domains=station.get("official_domains") or (),
            )
            if not retry:
                return initial
            retry_queries = tuple(item.query for item in retry)
            event("program_search_retry", {
                "failure_code": "empty_results",
                "queries": list(retry_queries),
                "families": [item.family for item in retry],
            })
            return run_program_search(retry_queries)

        # 英文 seedlist 名称与当地报道的简称、运营主体之间常没有一一对应关系。
        # 在实际搜索之前，请 DeepSeek 仅规划两条补充检索词；模型不返回 URL，
        # 也不会削弱下方对电站/年份/年度口径的硬校验。
        planner = getattr(self.agent, "suggest_search_queries", None)
        if getattr(self.agent, "enabled", True) and callable(planner) and (
            {"sse_disclosure", "deepseek_native_web_search", "program_controlled_search"} & providers
        ):
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
                        period_type=intent.period_type,
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
        if "sse_disclosure" in providers and str(station.get("country") or "").strip().lower() == "china":
            issuer_planner = getattr(self.agent, "suggest_listed_issuers", None)
            try:
                from .sse_disclosure import SseDisclosureProvider, deterministic_issuer_hints

                event("official_disclosure_search", {})
                # 先加入可审计的身份映射，再用模型补充不确定的上市主体。
                # 这样模型超时/返回空数组时，三峡系 seed 仍能走 600900 的
                # 交易所目录；最终正文仍必须核验具体电站，绝不自动写事实。
                issuers = deterministic_issuer_hints(station)
                if getattr(self.agent, "enabled", True) and callable(issuer_planner):
                    try:
                        suggested = issuer_planner(intent=intent, station=station)
                    except DeepSeekAgentError as exc:
                        warnings.append(f"上市公告主体识别不可用：{exc}")
                        suggested = []
                    if isinstance(suggested, list):
                        seen_codes = {str(item.get("security_code")) for item in issuers}
                        for item in suggested:
                            if not isinstance(item, dict):
                                continue
                            code = str(item.get("security_code") or "").strip()
                            if code and code not in seen_codes:
                                issuers.append(item)
                                seen_codes.add(code)
                            if len(issuers) >= 2:
                                break
                official = SseDisclosureProvider().discover(
                    issuers=issuers[:2], target_year=intent.target_period,
                )
                record_leads("sse_disclosure", official)
                all_candidates.extend(with_lead(official))
                event("official_disclosure_search_done", {"count": len(official)})
            except (ImportError, TypeError, ValueError) as exc:
                warnings.append(f"上市公告通道不可用：{exc}")

        # 通道 A：DeepSeek 原生联网搜索。失败不阻断独立搜索通道。
        if "deepseek_native_web_search" in providers:
            if not getattr(self.agent, "enabled", True):
                warnings.append("DeepSeek 原生搜索未配置；继续使用程序控制搜索")
            else:
                try:
                    event("deepseek_search", {})
                    native = self.agent.search(intent=intent, station=station)
                    record_leads("deepseek_native_web_search", native)
                    all_candidates.extend(with_lead(native))
                    event("deepseek_search_done", {"count": len(native)})
                except DeepSeekAgentError as exc:
                    warnings.append(f"DeepSeek 原生搜索异常（已继续程序搜索）：{exc}")

        # 通道 B：可审计的程序控制搜索，再由 DeepSeek 限定只能从真实结果中选择。
        if "program_controlled_search" in providers:
            try:
                event("program_search", {"queries": list(intent.query_hints)})
                # 始终走稳定的 ``search`` 入口，保证离线回放和第三方 provider
                # 替身不会被新诊断接口绕过。内建 provider 会在同次调用记录诊断。
                results = program_search_with_bounded_retry()
                search_event = {"count": len(results), "diagnostics": search_diagnostics}
                metrics = merged_search_metrics()
                if metrics:
                    search_event["metrics"] = metrics
                event("program_search_done", search_event)
                record_leads("program_controlled_search", results)
                # 先保存搜索引擎实际给出的 URL；模型仅能补充审核结论，不能作为
                # 候选存在与否的唯一决定者。
                all_candidates.extend(with_lead(self._program_candidates(results)))
                if getattr(self.agent, "enabled", True):
                    evaluated = self.agent.evaluate_search_results(intent=intent, station=station, results=results)
                    all_candidates.extend(with_lead(evaluated))
            except (WebSearchError, DeepSeekAgentError) as exc:
                warnings.append(f"程序搜索通道不可用：{exc}")

        # 通道 C：GEM 仅作为补充线索，不再单独形成“官方来源发现”的结果。
        # 官方站点模板、权威目录等补充候选不是搜索结果，不伪造 SearchLead；
        # 它们仍须和其他通道走同样的 URL 预检及相关性硬校验。
        all_candidates.extend(list(supplemental_candidates or []))
        if "gem_external_link" in providers:
            gem_values = list(gem_candidates or [])
            record_leads("gem_external_link", gem_values, "GEM external link")
            all_candidates.extend(with_lead(gem_values))
        merged = self._deduplicate(all_candidates)
        task = {
            "entity_id": station.get("entity_id"), "entity_name": station.get("canonical_name"),
            "target_period": intent.target_period, "metric": intent.metric,
        }
        ranked = self.scorer.rank_sources(merged, task)
        probed = self.url_probe.probe_many(ranked)
        # 搜索入口页本身可能没有数值，但其公开 PDF/Excel 附件才是真正证据。
        # 附件扩展完全有界，并会独立再次预检；不能把父页的 HTTP 200 当作
        # 附件可访问或可采集的证据。
        attachment_candidates = self.document_resolver.expand(
            probed, target_period=intent.target_period, metric=intent.metric,
        )
        if attachment_candidates:
            event("evidence_document_resolution", {"parent_count": len(probed), "attachment_count": len(attachment_candidates)})
            probed.extend(self.url_probe.probe_many(attachment_candidates))
            event("evidence_document_resolution_done", {"attachment_count": len(attachment_candidates)})

        # 预检后以最终重定向地址再次聚合。入口页与直链 PDF、或多个搜索引擎
        # 指向同一最终文档时，只保留一个候选，但把入口/重定向地址留在别名中。
        probed = SearchAggregator.merge(probed, prefer_final=True)

        qualified: list[dict[str, Any]] = []
        audited: list[dict[str, Any]] = []
        for candidate in probed:
            if candidate.get("access_status") not in {"reachable", "requires_browser"}:
                audited.append(candidate)
                continue
            relevance = self.verifier.verify(
                candidate, station=station, target_period=intent.target_period,
                metric=intent.metric, period_type=intent.period_type,
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
        candidate_task_id = task_id or f"trusted::{station.get('entity_id', 'unknown')}::{intent.target_period}"
        normalized = normalize_candidate_sources(qualified[:10], task_id=candidate_task_id)
        if ledger is not None:
            # 发现成功与实际下载是两件事：这里仅持久化已归一化候选，使
            # SearchLead → CandidateSource 可以审计；编排器实际访问 URL 时
            # 才会创建 SourceAttempt 并推进候选状态。
            if SourceAttemptLedger.is_available(self.conn):
                candidate_ledger = SourceAttemptLedger(self.conn)
                for candidate in normalized:
                    candidate_ledger.record_candidate(candidate)
            rejected_ids = [
                str(item.get("lead_id")) for item in audited
                if item.get("lead_id") and item.get("status") == "ineligible"
            ]
            ledger.update_status(rejected_ids, SearchLeadStatus.REJECTED)
            ledger.update_status(
                [str(item.lead_id) for item in normalized if item.lead_id],
                SearchLeadStatus.NORMALIZED,
            )
        return normalized, audited, warnings
