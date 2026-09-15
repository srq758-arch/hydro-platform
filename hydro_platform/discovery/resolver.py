"""Discovery 协调器：多通道来源发现（设计文档 §7）。

按通道尝试：
1. Level 1: GEM Wiki / Official Source Finder
2. Level 2: Authority Source Finder
3. Level 3: Google Custom Search（配置凭据时）
4. Level 4: DeepSeek 辅助发现（配置凭据时）

``min_candidates`` 曾被用作“找到足够候选后提前返回”的开关。那会让一个
由 URL 模板或泛化权威站点凑出的候选集阻止真实搜索通道运行，正是线上发现
质量不稳定的根源之一。现在它只作为兼容参数保留；每个已配置通道均独立执行，
失败也只记录在本通道诊断中，不能阻断其他通道。
"""

from __future__ import annotations
from typing import Any, Callable, List
import sqlite3

from ..common.logging_setup import get_logger
from ..reliability.scorer import ReliabilityScorer
from .official import OfficialSourceFinder, SourceCandidate
from .authority import AuthoritySourceFinder
from .deepseek_search import DeepSeekSourceFinder
from .google_search import GoogleSearchConfig, GoogleSearchDiscovery
from ..models.source_pipeline import CandidateSource
from ..common.enums import SearchLeadStatus
from ..pipeline.source_attempt_ledger import SourceAttemptLedger
from ..pipeline.source_contract_adapter import normalize_candidate_sources
from .search_lead_ledger import SearchLeadLedger

logger = get_logger(__name__)


class DiscoveryResolver:
    """数据源发现协调器"""

    def __init__(self, conn: sqlite3.Connection, deepseek_api_key: str = None):
        self.conn = conn
        self.scorer = ReliabilityScorer()

        # 初始化各级 Finder
        self.official_finder = OfficialSourceFinder(conn)
        self.authority_finder = AuthoritySourceFinder(conn)
        self.deepseek_finder = DeepSeekSourceFinder(api_key=deepseek_api_key)
        self.google_finder = None
        if GoogleSearchConfig.is_configured():
            api_key, engine_id = GoogleSearchConfig.from_env()
            self.google_finder = GoogleSearchDiscovery(api_key, engine_id)
            logger.info("Google Custom Search 来源发现已启用")
        else:
            logger.info("Google Custom Search 未配置，跳过该可选发现通道")
        # 面向任务运行记录的可审计诊断。每次 discover 都会重新初始化，避免
        # 把上一项电站的通道状态误展示给当前任务。
        self.last_diagnostics: list[dict[str, Any]] = []

    def _ledger_for_task(self, task: dict[str, Any]) -> SearchLeadLedger | None:
        """仅对已经落库的真实任务保留搜索线索。

        ``search_leads.task_id`` 是外键。手工诊断、旧兼容调用和规划页可能传入
        合成 ID；这些调用不能为方便审计而伪造一条任务记录。
        """
        task_id = str(task.get("task_id") or "").strip()
        if not task_id or not SearchLeadLedger.is_available(self.conn):
            return None
        exists = self.conn.execute(
            "SELECT 1 FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        return SearchLeadLedger(self.conn) if exists else None

    @staticmethod
    def _url_key(value: dict[str, Any]) -> str:
        return str(
            value.get("canonical_url") or value.get("final_url") or value.get("url") or ""
        ).strip().rstrip("/").lower()

    def _record_search_leads(
        self,
        ledger: SearchLeadLedger | None,
        *,
        task: dict[str, Any],
        provider: str,
        values: list[dict[str, Any]],
    ) -> dict[str, str]:
        """把真实搜索 API 的原始结果落入 SearchLead 台账。

        官方 URL 模板与 GEM 解析不是“搜索引擎原始结果”，故不在此伪造 lead；
        但它们会在返回前作为 CandidateSource 进入同一来源队列。
        """
        if ledger is None or not values:
            return {}
        return ledger.record_results(
            task_id=str(task["task_id"]),
            provider=provider,
            default_query=(
                f"{task.get('entity_name') or task.get('entity_id') or ''} "
                f"{task.get('target_period') or ''} {task.get('metric') or ''}"
            ).strip() or "source discovery",
            results=values,
        )

    @staticmethod
    def _annotate_leads(
        values: list[dict[str, Any]], lead_by_url: dict[str, str]
    ) -> list[dict[str, Any]]:
        annotated: list[dict[str, Any]] = []
        for value in values:
            key = str(
                value.get("canonical_url") or value.get("final_url") or value.get("url") or ""
            ).strip().rstrip("/").lower()
            lead_id = lead_by_url.get(key)
            annotated.append({**value, **({"lead_id": lead_id} if lead_id else {})})
        return annotated

    def _run_channel(
        self,
        *,
        name: str,
        callback: Callable[[], list[Any]],
    ) -> list[dict[str, Any]]:
        """隔离单通道异常，并把结果转换为可评分字典。"""
        try:
            raw = callback() or []
            values = [
                item.to_dict() if isinstance(item, SourceCandidate) else dict(item)
                for item in raw
                if item is not None
            ]
            self.last_diagnostics.append({"provider": name, "status": "ok", "count": len(values)})
            logger.info("Discovery 通道 %s 完成：%d 个候选", name, len(values))
            return values
        except Exception as exc:  # 每个 provider 的失败不能取消其他 provider
            self.last_diagnostics.append({
                "provider": name, "status": "error", "count": 0, "error": str(exc)[:500],
            })
            logger.warning("Discovery 通道 %s 失败: %s", name, exc)
            return []

    def discover(
        self,
        task: dict,
        min_candidates: int = 3,
        max_candidates: int = 10
    ) -> List[CandidateSource]:
        """执行多通道发现。

        Args:
            task: 任务信息
            min_candidates: 历史兼容参数；不再触发提前终止
            max_candidates: 最多候选数（截断）

        Returns:
            排序后的统一 CandidateSource 列表（按评分降序）
        """
        all_candidates: list[dict[str, Any]] = []
        self.last_diagnostics = []
        ledger = self._ledger_for_task(task)

        logger.info(f"开始 Discovery: entity_id={task.get('entity_id')}, period={task.get('target_period')}")

        # 没有“先找到三个就结束”的分支：四个可用通道全部调用。官方、权威
        # 页面也可能只提供导航或模板 URL，不能以它们的数量代替实际检索。
        official = self._run_channel(
            name="official_gem", callback=lambda: self.official_finder.find(task)
        )
        all_candidates.extend(official)
        authority = self._run_channel(
            name="authority", callback=lambda: self.authority_finder.find(task)
        )
        all_candidates.extend(authority)

        if self.google_finder is None:
            self.last_diagnostics.append({
                "provider": "google_custom_search", "status": "not_configured", "count": 0,
            })
        else:
            google = self._run_channel(
                name="google_custom_search", callback=lambda: self.google_finder.find(task, limit=5)
            )
            google_leads = self._record_search_leads(
                ledger, task=task, provider="google_custom_search", values=google,
            )
            all_candidates.extend(self._annotate_leads(google, google_leads))

        if not self.deepseek_finder.enabled:
            self.last_diagnostics.append({
                "provider": "deepseek_native_web_search", "status": "not_configured", "count": 0,
            })
        else:
            deepseek = self._run_channel(
                name="deepseek_native_web_search",
                callback=lambda: self.deepseek_finder.find(task, max_candidates=5),
            )
            deepseek_leads = self._record_search_leads(
                ledger, task=task, provider="deepseek_native_web_search", values=deepseek,
            )
            all_candidates.extend(self._annotate_leads(deepseek, deepseek_leads))

        # 如果没有找到任何候选
        if not all_candidates:
            logger.warning("Discovery 未找到任何候选来源")
            return []

        # 使用 Reliability Scorer 排序
        logger.info(f"对 {len(all_candidates)} 个候选进行评分排序")
        ranked_candidates = self.scorer.rank_sources(all_candidates, task)

        # 截断到 max_candidates
        task_id = str(
            task.get("task_id")
            or f"legacy::{task.get('entity_id', 'unknown')}::{task.get('target_period', 'unknown')}"
        )
        final_candidates = normalize_candidate_sources(
            ranked_candidates[:max_candidates],
            task_id=task_id,
        )

        # 已落库任务的所有实际候选均进入来源台账；此处仍不创建 acquisition
        # attempt，也不改变任务状态。SourceResolver/编排器在真正尝试访问某个
        # URL 时才创建 SourceAttempt。
        if ledger is not None and SourceAttemptLedger.is_available(self.conn):
            source_ledger = SourceAttemptLedger(self.conn)
            for candidate in final_candidates:
                source_ledger.record_candidate(candidate)
            ledger.update_status(
                [str(candidate.lead_id) for candidate in final_candidates if candidate.lead_id],
                SearchLeadStatus.NORMALIZED,
            )

        logger.info(f"Discovery 完成: 返回 {len(final_candidates)} 个候选（已排序）")

        # 打印 Top 3 候选
        for i, candidate in enumerate(final_candidates[:3], 1):
            logger.info(
                f"  #{i} {candidate.url} "
                f"(评分: {candidate.priority_score:.2f}, "
                f"类型: {candidate.source_type})"
            )

        return final_candidates
