"""Discovery/Search V2 的唯一编排服务。

页面上的“智能发现”、后台任务的自动补源、以及未来的批量工具不应各自拼接
搜索工具。它们都通过 :class:`SourceDiscoveryService` 提交一个明确请求，获得
同一份候选、排除项和 provider 诊断。服务只产生候选和审计线索；不会下载
正式资料、创建事实记录，亦不会绕过人工复核。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
import json
import re
import sqlite3

from ..discovery.authority import AuthoritySourceFinder
from ..discovery.identity_profile import build_station_identity_profile
from ..discovery.official import OfficialSourceFinder
from ..discovery.official_site_explorer import OfficialSiteExplorer
from ..discovery.operator_hints import deterministic_operator_hint
from ..discovery.url_probe import UrlProbe
from ..models.source_pipeline import CandidateSource
from .deepseek_agent import DeepSeekAgentError, DeepSeekResponsesAgent, TaskIntent
from .trusted_source_discovery import TrustedSourceDiscovery
from .web_search import WebSearchProvider


_DEFAULT_PROVIDERS = frozenset({
    "official_gem", "authority", "sse_disclosure", "deepseek_native_web_search",
    "program_controlled_search", "gem_external_link", "official_site_explorer",
})


@dataclass(frozen=True)
class SourceDiscoveryRequest:
    """单实体、单时期、单指标的来源发现请求。"""

    entity_id: str
    target_period: str
    metric: str = "generation"
    task_id: str | None = None
    source_policy: str = "official_or_authority"
    language: str | None = None
    query_hints: tuple[str, ...] = ()
    allowed_providers: frozenset[str] = _DEFAULT_PROVIDERS
    network_allowed: bool = True
    browser_allowed: bool = False
    max_candidates: int = 10

    def __post_init__(self) -> None:
        if not str(self.entity_id or "").strip():
            raise ValueError("entity_id 不能为空")
        if not str(self.target_period or "").strip().isdigit() or len(str(self.target_period)) != 4:
            raise ValueError("target_period 必须是四位年份")
        if self.metric not in {"generation", "capacity"}:
            raise ValueError("当前 Discovery 仅支持 generation 或 capacity")
        if self.max_candidates < 1 or self.max_candidates > 20:
            raise ValueError("max_candidates 必须在 1 到 20 之间")


@dataclass
class SourceDiscoveryResponse:
    """统一 Discovery 输出；候选和原始审计项严格分层。"""

    request: SourceDiscoveryRequest
    station: dict[str, Any]
    intent: TaskIntent
    candidates: list[CandidateSource] = field(default_factory=list)
    audited: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provider_diagnostics: list[dict[str, Any]] = field(default_factory=list)

    @property
    def metrics(self) -> dict[str, int]:
        return {
            "qualified_count": len(self.candidates),
            "audited_count": len(self.audited),
            "provider_count": len(self.provider_diagnostics),
            "provider_error_count": sum(
                1 for item in self.provider_diagnostics if item.get("status") == "error"
            ),
        }


class _UnavailableDeepSeekAgent:
    """没有密钥时的显式降级对象，不把“未配置”伪装成“没有结果”。"""

    enabled = False

    @staticmethod
    def _unavailable(*_args, **_kwargs):
        raise DeepSeekAgentError("未配置 DeepSeek API Key")

    suggest_search_queries = _unavailable
    suggest_listed_issuers = _unavailable
    search = _unavailable
    evaluate_search_results = _unavailable


class SourceDiscoveryService:
    """集中执行身份画像、查询族、多个搜索通道与硬校验。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        agent: DeepSeekResponsesAgent | None = None,
        deepseek_api_key: str | None = None,
        deepseek_model: str | None = None,
        web_search: WebSearchProvider | None = None,
        url_probe: UrlProbe | None = None,
        official_site_explorer: OfficialSiteExplorer | None = None,
    ) -> None:
        self.conn = conn
        self.agent = agent or (
            DeepSeekResponsesAgent(
                api_key=deepseek_api_key,
                model=deepseek_model or "deepseek-v4-flash",
            ) if deepseek_api_key else _UnavailableDeepSeekAgent()
        )
        self.web_search = web_search or WebSearchProvider()
        self.url_probe = url_probe or UrlProbe()
        self.official_site_explorer = official_site_explorer or OfficialSiteExplorer()

    @staticmethod
    def build_intent(
        station: dict[str, Any], target_period: str, metric: str = "generation",
    ) -> TaskIntent:
        """用同一身份画像生成可重复的基础查询族。

        DeepSeek 只可在后续补充别名/运营主体表达，不能覆盖这里由 seedlist
        生成的主查询。这样即便 LLM 或其联网工具不可用，仍有稳定、可审计的
        程序搜索路线。
        """
        canonical = str(station.get("canonical_name") or "").strip()
        local_name = str(station.get("local_name") or "").strip()
        raw_names = station.get("search_aliases") or station.get("aliases") or ()
        if isinstance(raw_names, str):
            text = raw_names.strip()
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = json.loads(text)
                    alias_names = [str(item).strip() for item in parsed] if isinstance(parsed, list) else [text]
                except (TypeError, ValueError):
                    alias_names = [item.strip() for item in re.split(r"[;,|/；、，]", text) if item.strip()]
            else:
                alias_names = [item.strip() for item in re.split(r"[;,|/；、，]", text) if item.strip()]
        else:
            alias_names = [str(item).strip() for item in raw_names if str(item).strip()]
        country = str(station.get("country") or "").strip().lower()
        names = list(dict.fromkeys(item for item in (local_name, *alias_names, canonical) if item))
        name = names[0] if names else canonical
        search_name = re.sub(r"^(?:长江|金沙江|雅砻江|澜沧江|黄河|珠江|红水河)", "", name)
        search_name = re.sub(r"水电(?:站|厂)$", "电站", search_name)
        is_chinese_name = bool(re.search(r"[\u4e00-\u9fff]", search_name))
        # 以 seedlist 的国家/本地名称决定首轮检索语言。之前土耳其、阿拉伯语
        # 词族只在“首轮无关/为空”的失败改写阶段触发，导致很多站点首轮只搜英文，
        # 在搜索引擎返回看似相关但不可用的页面时，补查可能根本不会执行。
        is_turkish = country in {"turkey", "türkiye", "turkiye"}
        is_arabic = country in {
            "egypt", "مصر", "sudan", "السودان", "iraq", "العراق",
            "syria", "سوريا", "morocco", "المغرب", "algeria", "الجزائر",
        } or bool(re.search(r"[\u0600-\u06ff]", search_name))
        publisher_profiles = station.get("publisher_profiles") or ()
        profile_publisher = next((
            str(item.get("canonical_name") or "").strip()
            for item in publisher_profiles if isinstance(item, dict)
        ), "")
        operator = str(
            station.get("operator")
            or station.get("owner")
            or profile_publisher
            or deterministic_operator_hint(station)
            or ""
        ).strip()
        if metric == "capacity":
            queries = [
                f'"{search_name}" {target_period} installed capacity MW',
                f'"{canonical}" {target_period} capacity report',
            ]
        elif country == "china" or is_chinese_name:
            queries = [
                f"{search_name} {target_period} 完成发电量",
                f"{search_name} {target_period} 全年 发电量",
            ]
            if operator:
                queries.append(f"{operator} {target_period} 发电量完成情况 {search_name}")
            else:
                queries.append(f"{search_name} {target_period} 发电量 年度报告")
        else:
            is_portuguese = country in {"brazil", "brasil", "portugal"}
            if is_portuguese:
                portuguese_name = re.sub(
                    r"^(?:usina\s+hidrel[eé]trica|central\s+hidrel[eé]trica)\s+",
                    "", name, flags=re.I,
                ).strip() or name
                queries = [
                    f'{portuguese_name} {target_period} geração anual',
                    f'{portuguese_name} {target_period} relatório anual geração',
                ]
            elif is_turkish:
                queries = [
                    f'"{search_name}" {target_period} yıllık elektrik üretimi',
                    f'"{search_name}" {target_period} yıllık faaliyet raporu üretim',
                ]
            elif is_arabic:
                queries = [
                    f'"{search_name}" {target_period} إنتاج الكهرباء السنوي',
                    f'"{search_name}" {target_period} التقرير السنوي إنتاج الكهرباء',
                ]
            else:
                queries = [
                    f'"{name}" {target_period} annual generation',
                    f'"{canonical}" {target_period} annual generation annual report',
                ]
            if operator:
                if is_portuguese:
                    queries.append(f'{operator} {target_period} geração {portuguese_name}')
                elif is_turkish:
                    queries.append(
                        f'"{operator}" {target_period} yıllık üretim raporu "{search_name}"'
                    )
                elif is_arabic:
                    queries.append(
                        f'"{operator}" {target_period} التقرير السنوي إنتاج "{search_name}"'
                    )
                else:
                    queries.append(f'"{operator}" {target_period} annual report "{name}" generation')
        # 只有已成功/已人工接受的官方域名才参与站内检索；未经核实的搜索结果
        # 不能自行变成“官方站点”。将它放在最后，保留一条泛查询防止旧域名失效。
        site_queries: list[str] = []
        for domain in station.get("official_domains") or ():
            domain = str(domain).strip()
            if not domain:
                continue
            if country == "china" and metric == "generation":
                # 三条查询预算内不能同时另开一条“运营方”查询时，把已验证
                # Publisher 名称并入 site: 查询，既不丢官网约束，也能提升
                # 大型集团公告中“电站简称未出现在标题”的召回率。
                publisher_term = f"{profile_publisher} " if profile_publisher else ""
                site_queries.append(f"site:{domain} {publisher_term}{search_name} {target_period} 发电量")
            elif metric == "generation":
                publisher_term = f' "{profile_publisher}"' if profile_publisher else ""
                site_queries.append(f'site:{domain}{publisher_term} "{search_name}" {target_period} generation')
            else:
                site_queries.append(f'site:{domain} "{search_name}" {target_period} capacity')
        return TaskIntent(
            station_name=name,
            target_period=str(target_period),
            metric=metric,
            source_policy="official_or_authority",
            # 已验证官方域名的站内查询优先于第三条泛查询，但绝不取代主查询。
            query_hints=tuple(dict.fromkeys(query for query in (queries[:2] + site_queries + queries[2:]) if query))[:3],
        )

    @staticmethod
    def build_generation_intent(station: dict[str, Any], target_period: str) -> TaskIntent:
        """兼容原 API 名称；新调用可指定任何已支持指标。"""
        return SourceDiscoveryService.build_intent(station, target_period, "generation")

    def _station(self, entity_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """SELECT entity_id, canonical_name, local_name, aliases, country, region,
                      river, capacity_mw, operator, owner, gem_wiki_url
               FROM stations WHERE entity_id=?""",
            (entity_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"未找到电站: {entity_id}")
        return dict(row)

    @staticmethod
    def _as_dict(values: Iterable[Any]) -> list[dict[str, Any]]:
        return [
            value.to_dict() if hasattr(value, "to_dict") else dict(value)
            for value in values if value is not None
        ]

    def _supplemental_candidates(
        self,
        *,
        station: dict[str, Any],
        intent: TaskIntent,
        providers: set[str],
        warnings: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """运行非搜索补充通道，并区分 GEM 外链与普通候选。"""
        task = {
            "entity_id": station["entity_id"], "entity_name": station["canonical_name"],
            "country": station.get("country"), "target_period": intent.target_period,
            "metric": intent.metric,
        }
        direct: list[dict[str, Any]] = []
        gem: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        if "official_gem" in providers or "gem_external_link" in providers:
            try:
                values = self._as_dict(OfficialSourceFinder(self.conn).find(task))
                gem = [
                    {**value, "discovery_method": "gem_wiki_external_link"}
                    for value in values if value.get("discovery_method") == "gem_wiki_external_link"
                ]
                direct = [
                    {**value, "discovery_method": value.get("discovery_method") or "official_url_pattern"}
                    for value in values if value.get("discovery_method") != "gem_wiki_external_link"
                ]
                if "official_gem" not in providers:
                    direct = []
                if "gem_external_link" not in providers:
                    gem = []
                diagnostics.append({
                    "provider": "official_gem", "status": "ok", "count": len(direct),
                    "gem_external_count": len(gem),
                })
            except Exception as exc:
                warnings.append(f"官网/GEM 外链通道不可用：{exc}")
                diagnostics.append({"provider": "official_gem", "status": "error", "count": 0, "error": str(exc)[:500]})
        if "authority" in providers:
            try:
                authority = [
                    {**value, "discovery_method": value.get("discovery_method") or "authority_directory"}
                    for value in self._as_dict(AuthoritySourceFinder(self.conn).find(task))
                ]
                direct.extend(authority)
                diagnostics.append({"provider": "authority", "status": "ok", "count": len(authority)})
            except Exception as exc:
                warnings.append(f"权威目录通道不可用：{exc}")
                diagnostics.append({"provider": "authority", "status": "error", "count": 0, "error": str(exc)[:500]})
        if "official_site_explorer" in providers:
            domains = station.get("official_domains") or ()
            if not domains:
                diagnostics.append({
                    "provider": "official_site_explorer", "status": "skipped", "count": 0,
                    "reason": "尚无历史成功或人工接受的官方域名",
                })
            else:
                try:
                    known_report_paths: dict[str, list[str]] = {}
                    for profile in station.get("publisher_profiles") or ():
                        if not isinstance(profile, dict):
                            continue
                        domain = str(profile.get("official_domain") or "").strip().lower().removeprefix("www.")
                        paths = profile.get("report_path_patterns")
                        if domain and isinstance(paths, (list, tuple)):
                            known_report_paths.setdefault(domain, []).extend(
                                str(path).strip() for path in paths if str(path).strip()
                            )
                    explored = self.official_site_explorer.discover(
                        official_domains=domains,
                        official_entry_urls=station.get("official_entry_urls") or (),
                        known_report_paths=known_report_paths,
                        target_period=intent.target_period,
                    )
                    direct.extend(explored)
                    diagnostics.append({
                        "provider": "official_site_explorer", "status": "ok", "count": len(explored),
                    })
                except Exception as exc:
                    warnings.append(f"已验证官网站内探索不可用：{exc}")
                    diagnostics.append({
                        "provider": "official_site_explorer", "status": "error", "count": 0,
                        "error": str(exc)[:500],
                    })
        return direct, gem, diagnostics

    def discover(
        self,
        request: SourceDiscoveryRequest,
        *,
        intent: TaskIntent | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> SourceDiscoveryResponse:
        """执行一次独立、可审计的来源发现。"""
        station = build_station_identity_profile(self.conn, self._station(request.entity_id)).station_context()
        profile_intent = self.build_intent(station, request.target_period, request.metric)
        if intent is None:
            resolved_intent = profile_intent
        else:
            # 用户自然语言计划给出的检索词是补充，而非覆盖 seedlist/已验证
            # Publisher Profile 的固定主查询。二者去重后共用同一三条查询预算。
            resolved_intent = TaskIntent(
                station_name=intent.station_name or profile_intent.station_name,
                target_period=intent.target_period,
                metric=intent.metric,
                source_policy=intent.source_policy,
                auto_execute=intent.auto_execute,
                query_hints=tuple(dict.fromkeys(
                    (*profile_intent.query_hints, *intent.query_hints)
                ))[:3],
            )
        if resolved_intent.target_period != str(request.target_period) or resolved_intent.metric != request.metric:
            raise ValueError("Discovery intent 必须与请求的目标时期和指标一致")
        providers = set(request.allowed_providers)
        if not request.network_allowed:
            return SourceDiscoveryResponse(
                request=request, station=station, intent=resolved_intent,
                warnings=["本次请求未授予网络权限，未执行来源发现"],
                provider_diagnostics=[{"provider": "network", "status": "disabled", "count": 0}],
            )

        warnings: list[str] = []
        supplemental, gem, diagnostics = self._supplemental_candidates(
            station=station, intent=resolved_intent, providers=providers, warnings=warnings,
        )
        events: list[tuple[str, dict[str, Any]]] = []

        def emit(stage: str, payload: dict[str, Any]) -> None:
            events.append((stage, dict(payload)))
            if on_event:
                on_event(stage, payload)

        engine = TrustedSourceDiscovery(
            agent=self.agent,
            web_search=self.web_search,
            url_probe=self.url_probe,
            conn=self.conn,
        )
        candidates, audited, engine_warnings = engine.discover(
            intent=resolved_intent,
            station=station,
            gem_candidates=gem,
            supplemental_candidates=supplemental,
            task_id=request.task_id,
            enabled_providers=providers,
            on_event=emit,
        )
        # Engine 的完成事件包含真实的每引擎诊断；保留它们而不是把“有候选”
        # 误当作所有 provider 成功。
        for stage, payload in events:
            if stage == "program_search_done":
                entries = payload.get("diagnostics")
                if isinstance(entries, list):
                    diagnostics.extend(entries)
                else:
                    diagnostics.append({"provider": "program_controlled_search", "status": "ok", "count": payload.get("count", 0)})
                metrics = payload.get("metrics")
                if isinstance(metrics, dict) and metrics:
                    diagnostics.append({
                        "provider": "program_controlled_search",
                        "status": "metrics",
                        "count": payload.get("count", 0),
                        "metrics": metrics,
                    })
            elif stage in {"deepseek_search_done", "official_disclosure_search_done"}:
                diagnostics.append({
                    "provider": "deepseek_native_web_search" if stage == "deepseek_search_done" else "sse_disclosure",
                    "status": "ok", "count": payload.get("count", 0),
                })
        if "deepseek_native_web_search" in providers and not getattr(self.agent, "enabled", True):
            diagnostics.append({"provider": "deepseek_native_web_search", "status": "not_configured", "count": 0})
        return SourceDiscoveryResponse(
            request=request,
            station=station,
            intent=resolved_intent,
            candidates=candidates[:request.max_candidates],
            audited=audited,
            warnings=warnings + engine_warnings,
            provider_diagnostics=diagnostics,
        )


class TaskSourceDiscoveryAdapter:
    """把统一服务适配为历史 Pipeline 所需的 ``discover`` 窄接口。

    这是单向兼容边界：Pipeline 只消费 ``CandidateSource``，不会重新回到旧
    discovery 字典。保留最后响应仅用于任务详情诊断，不影响执行语义。
    """

    def __init__(self, service: SourceDiscoveryService) -> None:
        self.service = service
        self.last_response: SourceDiscoveryResponse | None = None

    def discover(
        self,
        task: dict[str, Any],
        min_candidates: int = 3,  # noqa: ARG002 - 历史接口兼容，不能提前终止
        max_candidates: int = 10,
    ) -> list[CandidateSource]:
        response = self.service.discover(SourceDiscoveryRequest(
            task_id=str(task.get("task_id") or "").strip() or None,
            entity_id=str(task.get("entity_id") or ""),
            target_period=str(task.get("target_period") or ""),
            metric=str(task.get("metric") or "generation"),
            source_policy=str(task.get("source_policy") or "official_or_authority"),
            query_hints=tuple(str(item) for item in task.get("query_hints", []) if item),
            max_candidates=max(1, min(int(max_candidates), 20)),
        ))
        self.last_response = response
        return response.candidates
