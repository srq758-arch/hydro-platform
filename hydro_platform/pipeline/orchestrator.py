"""管线编排器（文档 §22 步骤 14 / §25 单任务闭环）。

run_task：领取任务 → 采集 → 归档 → 解析 → 抽取 → 校验 → 存证 → 复核闸门。
干净的非 Top100 候选自动升级为 publishable；需复核者（含全部 Top100）入队并把
任务落到 needs_review，停在人工断点。apply_review_decision：人工 approve 后
调 promote_candidate 升级，reject 则驳回。全过程幂等、失败诚实（写 FailureStage）。
"""

from __future__ import annotations

import hashlib
import json

from ..common.enums import FailureStage, Severity, TaskStatus
from ..common.clock import now_iso
from ..common.logging_setup import get_logger
from ..models.source import Source
from ..archive.archiver import Archiver
from ..database.repositories import (
    ReviewRepository,
    SourceRepository,
    TaskRunRepository,
)
from ..evidence.store import EvidenceStore
from ..extraction.rule_extractors import extract_candidates
from ..parsing.dispatcher import parse_document
from ..review.queue import ReviewQueue
from ..tasking.manager import TaskManager
from ..validation.engine import ValidationContext, validate_candidate
from .context import PipelineContext
from .result import PipelineResult
from .error_handler import PipelineError, wrap_stage
from .source_resolver import resolve_sources_enhanced
from ..registry.source_registry import SourceRegistry
from .entity_attribution import validate_entity_attribution
from .candidate_evidence_binding import (
    create_candidate_with_evidence,
    CandidateEvidenceError
)

logger = get_logger(__name__)


class TaskCancelled(Exception):
    """任务在管线运行期间被外部取消，不能按普通失败处理。"""


def _entity_facts(ctx: PipelineContext, entity_id: str) -> tuple:
    """返回 (capacity_mw, is_top100)。优先用注入的 lookup，否则查 stations。"""
    if ctx.entity_lookup is not None:
        return ctx.entity_lookup(entity_id)
    row = ctx.conn.execute(
        "SELECT capacity_mw, priority_tier FROM stations WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()
    if row is None:
        return (None, False)
    # priority_tier == 'A' 视作 Top100 相关（保守：旗舰站必复核）
    is_top100 = (row["priority_tier"] or "").upper() == "A"
    return (row["capacity_mw"], is_top100)


def _entity_names(ctx: PipelineContext, entity_id: str) -> tuple[str, ...]:
    """返回目标站的规范名、当地名和别名，供表格行级归属使用。"""
    row = ctx.conn.execute(
        "SELECT canonical_name, local_name, aliases FROM stations WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()
    if row is None:
        return ()
    names = [row["canonical_name"], row["local_name"]]
    raw_aliases = row["aliases"]
    if raw_aliases:
        try:
            aliases = json.loads(raw_aliases)
            names.extend(aliases if isinstance(aliases, list) else [])
        except (TypeError, json.JSONDecodeError):
            names.extend(part.strip() for part in str(raw_aliases).split(","))
    return tuple(str(name).strip() for name in names if name and str(name).strip())


def _parsed_evidence_text(parsed) -> str:
    """将解析出的表格转成带表头的可审计文本，供归属校验与 LLM 阅读。"""
    parts = [getattr(parsed, "text", "") or ""]
    for index, table in enumerate(getattr(parsed, "tables", []) or []):
        heading = f"表格 {index + 1}" + (f"（{table.caption}）" if table.caption else "")
        if table.headers:
            parts.append(heading + "：" + " | ".join(table.headers))
        for row in table.rows:
            parts.append(" | ".join(row))
    return "\n".join(part for part in parts if part)


def run_task(ctx: PipelineContext, task) -> PipelineResult:
    """把一个任务跑到复核闸门。返回 PipelineResult，全过程更新 tasks 状态。

    P0-4修复：所有执行都写入 task_runs 审计。
    P0-5修复：统一异常处理，确保任务不会卡在 running。
    """
    tm = TaskManager(ctx.conn)
    task_run_repo = TaskRunRepository(ctx.conn)

    result = PipelineResult(
        task_id=task.task_id,
        final_status=TaskStatus.RUNNING,
        reached_stage="claim",
    )

    # —— 幂等闸门：终态/待复核任务不重复执行（可安全重跑，文档 §25）——
    row = tm.repo.get(task.task_id)
    current = TaskStatus(row["status"]) if row is not None else TaskStatus.PENDING
    if current in (TaskStatus.SUCCESS, TaskStatus.CANCELLED):
        result.final_status = current
        result.reached_stage = "noop_terminal"
        result.record("idempotency", True, f"任务已处于终态 {current.value}，跳过")
        return result
    if current is TaskStatus.NEEDS_REVIEW:
        result.final_status = current
        result.reached_stage = "review_gate"
        result.record("idempotency", True, "任务待人工复核，跳过重跑")
        return result
    if current is TaskStatus.FAILED:
        # 失败任务重跑：先回排到 pending（受 max_attempts 约束），再走正常领取
        tm.requeue(task.task_id)

    tm.claim(task.task_id)

    # —— P0-4: 创建 task_run 审计记录 ——
    attempt = (row["attempts"] if row else 0) + 1
    run_id = task_run_repo.create_run(task.task_id, attempt)
    logger.info(f"任务 {task.task_id} 开始执行（第 {attempt} 次尝试，run_id={run_id}）")

    # —— P0-5: 统一异常处理包装 ——
    try:
        # 执行完整的 Pipeline 流程
        _execute_pipeline(ctx, task, tm, result)

        # 成功：更新 task_runs
        task_run_repo.update_run_success(
            run_id=run_id,
            message=f"Success: {result.candidates_extracted} candidates, "
                   f"{len(result.review_ids)} needs review"
        )
        logger.info(f"任务 {task.task_id} 执行成功")
        return result

    except PipelineError as pe:
        # Pipeline 阶段失败：记录失败阶段
        logger.error(f"任务 {task.task_id} 失败于 {pe.stage.value}: {pe.message}")

        task_run_repo.update_run_failure(
            run_id=run_id,
            failure_stage=pe.stage.value,
            message=pe.message
        )

        tm.mark_failed(task.task_id, failure_stage=pe.stage, last_error=pe.message)

        result.final_status = TaskStatus.FAILED
        result.reached_stage = "failed"
        result.failure_stage = pe.stage
        result.error = pe.message
        result.record(pe.stage.value, False, pe.message)
        return result

    except TaskCancelled as exc:
        task_run_repo.update_run_failure(
            run_id=run_id,
            failure_stage="CANCELLED",
            message=str(exc),
        )
        result.final_status = TaskStatus.CANCELLED
        result.reached_stage = "cancelled"
        result.error = str(exc)
        result.record("cancelled", True, str(exc))
        return result

    except Exception as e:
        # 未知异常
        logger.error(f"任务 {task.task_id} 遇到未知异常: {e}", exc_info=True)

        task_run_repo.update_run_failure(
            run_id=run_id,
            failure_stage=FailureStage.UNKNOWN.value,
            message=f"Unexpected error: {str(e)}"
        )

        tm.mark_failed(
            task.task_id,
            failure_stage=FailureStage.UNKNOWN,
            last_error=f"Unexpected: {str(e)}"
        )

        result.final_status = TaskStatus.FAILED
        result.reached_stage = "failed"
        result.failure_stage = FailureStage.UNKNOWN
        result.error = f"Unexpected error: {str(e)}"
        result.record(FailureStage.UNKNOWN.value, False, result.error)
        return result


def _execute_pipeline(ctx: PipelineContext, task, tm: TaskManager, result: PipelineResult) -> None:
    """执行完整的 Pipeline 流程（内部函数，供 run_task 调用）。

    所有阶段的异常都应该被包装为 PipelineError。
    """

    _ensure_task_active(ctx, task)

    # —— 采集：增强版来源解析（SourceRegistry → Discovery → Fallback）——
    refs = resolve_sources_enhanced(
        conn=ctx.conn,
        task=task,
        fallback_resolver=ctx.url_resolver,
        discovery_resolver=ctx.discovery_resolver,
    )
    if not refs:
        raise PipelineError(FailureStage.DISCOVERY_FAILED, "无可采集来源")

    capacity_mw, is_top100 = _entity_facts(ctx, task.entity_id)
    entity_names = _entity_names(ctx, task.entity_id)
    expected_year = _parse_year(task.target_period)

    all_candidates = []
    registry = SourceRegistry(ctx.conn)  # 用于更新来源评分

    for ref in refs:
        _ensure_task_active(ctx, task)
        current_source_id = None  # 记录当前来源ID，用于更新评分

        try:
            fetched = ctx.router.fetch(ref.url, expected=ref.expected)
            if not fetched.success:
                code = fetched.error_code.value if fetched.error_code else "?"

                # 采集失败：更新来源评分
                if current_source_id:
                    registry.update_failure(
                        current_source_id,
                        reason=f"采集失败[{code}]",
                        stage="acquisition"
                    )

                raise PipelineError(
                    FailureStage.ACQUISITION_FAILED,
                    f"采集失败[{code}]: {ref.url}"
                )
            result.record("acquisition", True, ref.url)
        except PipelineError:
            raise
        except Exception as e:
            # 采集异常：更新来源评分
            if current_source_id:
                registry.update_failure(
                    current_source_id,
                    reason=str(e),
                    stage="acquisition"
                )

            raise PipelineError(
                FailureStage.ACQUISITION_FAILED,
                f"采集异常: {ref.url}",
                cause=e
            )

        _ensure_task_active(ctx, task)

        # —— 登记来源（FK 锚点）+ 归档 ——
        try:
            src_id = _register_source(ctx, ref, fetched, task)
            current_source_id = src_id  # 保存source_id供后续使用

            archiver = Archiver(ctx.conn, raw_root=ctx.raw_root)
            arch = archiver.archive(
                fetched, entity_id=task.entity_id, task_id=task.task_id, source_id=src_id
            )
            if arch.newly_archived:
                result.documents_archived += 1
            result.record("archive", True, arch.document.document_id)

            # 归档成功：更新来源评分（采集+归档都成功）
            registry.update_success(src_id, document_id=arch.document.document_id)

        except Exception as e:
            # 归档失败：更新来源评分
            if current_source_id:
                registry.update_failure(
                    current_source_id,
                    reason=f"归档失败: {str(e)}",
                    stage="archive"
                )

            raise PipelineError(
                FailureStage.ARCHIVE_FAILED,
                f"归档失败: {ref.url}",
                cause=e
            )

        _ensure_task_active(ctx, task)

        # —— 解析 ——
        try:
            parsed = parse_document(
                arch.local_path,
                arch.document.content_kind,
                content_type=arch.document.content_type,
            )
            if not parsed.ok:
                raise PipelineError(
                    FailureStage.PARSE_FAILED,
                    f"解析失败: {parsed.error or arch.document.content_kind}"
                )
            result.record("parsing", True, f"{len(parsed.tables)} tables")
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError(
                FailureStage.PARSE_FAILED,
                f"解析异常: {arch.document.content_kind}",
                cause=e
            )

        # —— 抽取（规则为真实路径；可选叠加 LLM）——
        try:
            cands = extract_candidates(
                parsed,
                entity_id=task.entity_id,
                task_id=task.task_id,
                source_id=src_id,
                entity_names=entity_names,
            )
            if ctx.use_llm and ctx.llm_provider is not None:
                cands.extend(_llm_candidates(ctx, parsed, task, src_id))
            # 把归档信息挂到候选上，供存证阶段引用（不改模型，用局部元组携带）
            for c in cands:
                # 抽取器（尤其是插件/测试替身）不能决定当前任务和已登记来源。
                # 以执行上下文覆盖这两个 FK 锚点，避免过期元数据写入候选表。
                c.task_id = task.task_id
                c.source_id = src_id
                if c.entity_id is None:
                    c.entity_id = task.entity_id
                all_candidates.append(
                    (c, arch.document.document_id, arch.document.content_hash, ref, parsed)
                )
        except Exception as e:
            raise PipelineError(
                FailureStage.EXTRACTION_FAILED,
                "抽取异常",
                cause=e
            )

    if not all_candidates:
        raise PipelineError(FailureStage.EXTRACTION_EMPTY, "未抽出任何候选")
    result.candidates_extracted = len(all_candidates)
    result.record("extraction", True, f"{len(all_candidates)} candidates")

    # —— 校验 + 存证 + 复核闸门 ——
    try:
        store = EvidenceStore(ctx.conn)
        queue = ReviewQueue(ctx.conn)
        vctx = ValidationContext(
            entity_capacity_mw=capacity_mw, expected_year=expected_year
        )
    except Exception as e:
        raise PipelineError(
            FailureStage.UNKNOWN,
            "初始化存证/复核队列失败",
            cause=e
        )

    # 无发电量值的候选不是「发电量事实主张」——按文档 13.3「没有公开数据 ≠ 0」，
    # 缺值不构成对发电量的声明（多为容量误读等噪声/告警）。它们不进事实管线，
    # 既不入复核也不升级，避免与真实主张撞自然键。仅记审计说明。
    fact_candidates = [
        t for t in all_candidates if t[0].generation_gwh is not None
    ]
    noise_count = len(all_candidates) - len(fact_candidates)
    if noise_count:
        result.record("extraction", True, f"{noise_count} 个无值候选(噪声/告警)已剔除")
    if not fact_candidates:
        raise PipelineError(
            FailureStage.EXTRACTION_EMPTY,
            "仅抽出无发电量值的候选，无可升级/复核的事实主张"
        )

    needs_human = False
    promotable = []  # (candidate, validation, evidence_id) 干净可自动升级者

    try:
        for cand, doc_id, content_hash, ref, candidate_parsed in fact_candidates:
            _ensure_task_active(ctx, task)
            # D05: 实体归属不是日志提示。验证失败的候选不得自动升级，必须进入
            # Review Queue；验证本身发生异常则让任务失败，不能以“忽略异常”发布。
            evidence_text = _parsed_evidence_text(candidate_parsed)
            try:
                attribution_valid, attribution_reason = validate_entity_attribution(
                    conn=ctx.conn,
                    entity_id=cand.entity_id,
                    source_text=evidence_text,
                )
            except Exception as e:
                raise PipelineError(
                    FailureStage.VALIDATION_FAILED,
                    f"D05 实体归属验证执行失败: {e}",
                    cause=e,
                ) from e

            # 原有校验流程
            val = validate_candidate(cand, vctx)
            if not attribution_valid:
                val.add_issue(
                    "ENTITY_ATTRIBUTION_FAILED",
                    attribution_reason,
                    Severity.HIGH,
                    "entity_id",
                )
            candidate_id = _candidate_id(cand, doc_id)
            cand.candidate_id = candidate_id
            eid = store.save_for_candidate(
                cand,
                document_id=doc_id,
                content_hash=content_hash,
                source_url=ref.url,
            )

            # D06: 创建候选记录并关联证据（不可变绑定）
            try:
                candidate_id = create_candidate_with_evidence(
                    conn=ctx.conn,
                    candidate_id=candidate_id,
                    task_id=cand.task_id,
                    entity_id=cand.entity_id,
                    document_id=doc_id,
                    evidence_ids=[eid],  # 强制非空，不可变
                    period_type=cand.period_type,
                    period_label=cand.period_label,
                    value_type=cand.value_type,
                    measurement_scope=cand.measurement_scope,
                    generation_gwh=cand.generation_gwh,
                    value_raw=cand.value_raw,
                    unit_raw=cand.unit_raw,
                    snippet=cand.snippet,
                    extraction_method=cand.extractor or 'rule'
                )
                logger.debug(f"D06 候选 {candidate_id} 已关联证据 {eid}")
            except CandidateEvidenceError as e:
                logger.error(f"D06 创建候选-证据关联失败: {e}")
                raise PipelineError(
                    FailureStage.VALIDATION_FAILED,
                    f"候选-证据关联失败: {e}"
                )

            rid = queue.submit(cand, val, evidence_ids=[eid], is_top100=is_top100)
            if rid is not None:
                needs_human = True
                if rid not in result.review_ids:
                    result.review_ids.append(rid)
            elif val.passed:
                promotable.append((cand, val, eid))
        result.record("validation+evidence", True, f"{len(all_candidates)} checked")
    except PipelineError:
        # 保留明确的失败阶段和原因，不能再包成无上下文的通用错误。
        raise
    except Exception as e:
        logger.exception("校验/存证/复核提交出现未分类异常")
        raise PipelineError(
            FailureStage.VALIDATION_FAILED,
            f"校验/存证/复核提交失败: {e}",
            cause=e
        ) from e

    # —— 自动升级干净候选（非 Top100 且校验通过且无需复核）——
    try:
        for cand, val, eid in promotable:
            _ensure_task_active(ctx, task)
            _promote(ctx, result, cand, val, eid, review_required=False)
    except Exception as e:
        raise PipelineError(
            FailureStage.DATABASE_WRITE_FAILED,
            "自动升级失败",
            cause=e
        )

    # —— 收尾：有需复核者 → needs_review 停在断点；否则 success ——
    _ensure_task_active(ctx, task)
    if needs_human:
        tm.mark_needs_review(
            task.task_id, last_error=f"{len(result.review_ids)} 项待复核"
        )
        result.final_status = TaskStatus.NEEDS_REVIEW
        result.reached_stage = "review_gate"
        logger.info("任务 %s 停在复核断点：%s", task.task_id, result.review_ids)
    else:
        tm.mark_success(task.task_id)
        result.final_status = TaskStatus.SUCCESS
        result.reached_stage = "promotion"


def apply_review_decision(
    ctx: PipelineContext,
    task,
    review_id: str,
    decision: str,
    reason: str = None,
) -> PipelineResult:
    """人工复核决策落地（文档 §15）。approve → 升级；reject → 驳回任务。

    从 review_items 载荷重建候选并升级。需 ctx.review_decider 无关——决策由参数给。

    P0-6修复：Promotion失败时正确标记任务为failed，不伪装为success。

    Args:
        ctx: Pipeline上下文
        task: 任务对象
        review_id: 复核项ID
        decision: 决策（approve/reject）
        reason: 拒绝原因（可选，仅在reject时使用）
    """
    tm = TaskManager(ctx.conn)
    task_run_repo = TaskRunRepository(ctx.conn)
    queue = ReviewQueue(ctx.conn)

    result = PipelineResult(
        task_id=task.task_id,
        final_status=TaskStatus.NEEDS_REVIEW,
        reached_stage="review_decision",
    )

    # 创建 task_run 审计记录（复核操作）
    row = tm.repo.get(task.task_id)
    attempt = (row["attempts"] if row else 0) + 1
    run_id = task_run_repo.create_run(task.task_id, attempt)
    logger.info(f"复核决策 {review_id}: {decision}")

    try:
        queue.decide(review_id, decision, reviewer=ctx.reviewer)

        if str(decision) == "reject":
            reject_message = f"复核驳回 {review_id}"
            if reason:
                reject_message += f": {reason}"

            # D09修复：reject同步所有相关表
            review_row = ReviewRepository(ctx.conn).get(review_id)
            if review_row:
                candidate_id = review_row['candidate_id']

                try:
                    import json
                    from hydro_platform.common.clock import now_iso

                    # 1. 更新 extraction_candidates.review_status
                    if candidate_id:
                        ctx.conn.execute("""
                            UPDATE extraction_candidates
                            SET review_status = 'rejected'
                            WHERE candidate_id = ?
                        """, (candidate_id,))

                    # 2. 记录到 review_events 表
                    import uuid
                    event_id = f"evt_{uuid.uuid4().hex[:12]}"
                    ctx.conn.execute("""
                        INSERT INTO review_events
                        (event_id, review_id, candidate_id, action, decision, reviewer, reason, created_at)
                        VALUES (?, ?, ?, 'decide', 'reject', ?, ?, ?)
                    """, (event_id, review_id, candidate_id, ctx.reviewer or 'system', reason, now_iso()))

                    # 3. 更新 generation_records 状态（如果已有记录）
                    payload = json.loads(review_row['payload'] or '{}')
                    cand = payload.get('candidate', {})
                    entity_id = review_row['entity_id']
                    period_label = cand.get('period_label')
                    value_type = cand.get('value_type', 'actual')

                    if entity_id and period_label:
                        ctx.conn.execute("""
                            UPDATE generation_records
                            SET publication_status = 'withheld',
                                review_status = 'rejected',
                                updated_at = ?
                            WHERE entity_id = ?
                              AND period_label = ?
                              AND value_type = ?
                              AND (publication_status = 'draft' OR review_status = 'open')
                        """, (now_iso(), entity_id, str(period_label), value_type))

                    ctx.conn.commit()
                except Exception as e:
                    logger.warning(f"同步拒绝状态失败: {e}")
                    ctx.conn.rollback()

            # 4. 只有全部候选均已裁决时才能结束父任务。拒绝其中一条
            # 不能阻断同一采集任务里的其他 open 复核项。
            remaining = [
                r for r in queue.repo.open_items() if r["task_id"] == task.task_id
            ]
            if not remaining:
                try:
                    tm.reject(task.task_id, last_error=reject_message)
                except Exception as e:
                    logger.warning(f"任务不存在或已终态，仅关闭复核项: {task.task_id}, {e}")

            result.final_status = TaskStatus.FAILED
            result.failure_stage = FailureStage.REVIEW_REJECTED
            result.record("review_decision", True, f"rejected: {reason}" if reason else "rejected")

            task_run_repo.update_run_success(
                run_id=run_id,
                message=f"Review rejected: {review_id}" + (f" - {reason}" if reason else "")
            )
            return result

        # D03修复：request_more_evidence 明确处理，不发布
        if str(decision) == "request_more_evidence":
            # 保持 needs_review 状态，等待补充证据
            result.final_status = TaskStatus.NEEDS_REVIEW
            result.record("review_decision", True, "request_more_evidence")

            # 记录审计
            task_run_repo.update_run_success(
                run_id=run_id,
                message=f"Review requesting more evidence: {review_id}"
            )
            logger.info(f"复核项 {review_id} 要求补充证据，保持待复核状态")
            return result

        # 只有明确的 approve 才进入升级分支
        if str(decision) != "approve":
            # 拒绝未知决策
            raise PipelineError(
                FailureStage.REVIEW_REJECTED,
                f"未知的复核决策: {decision}，仅支持 approve/reject/request_more_evidence"
            )

        # approve：从载荷重建候选并升级
        review_row = ReviewRepository(ctx.conn).get(review_id)
        if review_row is None:
            raise PipelineError(
                FailureStage.REVIEW_REJECTED,
                f"复核项不存在 {review_id}"
            )

        cand, val, eid = _rebuild_from_review(ctx, review_row, task)

        # P0-6关键修复：_promote 现在会抛出异常而不是静默失败
        _promote(ctx, result, cand, val, eid, review_required=True)

        # D12修复：approve同步generation_records状态
        try:
            import json
            import uuid
            from hydro_platform.common.clock import now_iso

            candidate_id = review_row['candidate_id']

            # 1. 更新 extraction_candidates.review_status
            if candidate_id:
                ctx.conn.execute("""
                    UPDATE extraction_candidates
                    SET review_status = 'approved'
                    WHERE candidate_id = ?
                """, (candidate_id,))

            # 2. 记录到 review_events 表
            event_id = f"evt_{uuid.uuid4().hex[:12]}"
            ctx.conn.execute("""
                INSERT INTO review_events
                (event_id, review_id, candidate_id, action, decision, reviewer, reason, created_at)
                VALUES (?, ?, ?, 'decide', 'approve', ?, NULL, ?)
            """, (event_id, review_id, candidate_id, ctx.reviewer or 'system', now_iso()))

            # 3. 更新 generation_records 的 review_status 和 validation_status
            payload = json.loads(review_row['payload'] or '{}')
            entity_id = review_row['entity_id']
            period_label = cand.period_label
            value_type = cand.value_type

            if entity_id and period_label:
                # 找到对应的 generation_records 记录并更新
                ctx.conn.execute("""
                    UPDATE generation_records
                    SET review_status = 'approved',
                        validation_status = 'validated',
                        evidence_id = ?,
                        updated_at = ?
                    WHERE entity_id = ?
                      AND period_label = ?
                      AND value_type = ?
                """, (eid, now_iso(), entity_id, str(period_label), value_type))

            ctx.conn.commit()
        except Exception as e:
            logger.warning(f"同步审批状态失败: {e}")
            ctx.conn.rollback()

        # 若该任务再无未决复核项，则整体 success
        remaining = [
            r for r in queue.repo.open_items() if r["task_id"] == task.task_id
        ]
        if not remaining:
            tm.approve(task.task_id)
            result.final_status = TaskStatus.SUCCESS

        result.record("review_decision", True, "approved")

        # 记录审计
        task_run_repo.update_run_success(
            run_id=run_id,
            message=f"Review approved and promoted: {review_id}"
        )
        return result

    except PipelineError as pe:
        # Promotion 失败
        logger.error(f"复核决策失败: {pe.message}")

        task_run_repo.update_run_failure(
            run_id=run_id,
            failure_stage=pe.stage.value,
            message=pe.message
        )

        current_task = tm.repo.get(task.task_id)
        if current_task is not None and current_task["status"] != TaskStatus.FAILED.value:
            tm.mark_failed(
                task.task_id,
                failure_stage=pe.stage,
                last_error=f"Promotion failed: {pe.message}"
            )

        result.final_status = TaskStatus.FAILED
        result.failure_stage = pe.stage
        result.error = pe.message
        result.record("review_decision", False, pe.message)
        return result

    except Exception as e:
        # 未知错误
        logger.error(f"复核决策遇到未知异常: {e}", exc_info=True)

        task_run_repo.update_run_failure(
            run_id=run_id,
            failure_stage=FailureStage.REVIEW_REJECTED.value,
            message=f"Unexpected error: {str(e)}"
        )

        # 如果task存在，标记为失败
        try:
            current_task = tm.repo.get(task.task_id)
            if current_task is not None and current_task["status"] != TaskStatus.FAILED.value:
                tm.mark_failed(
                    task.task_id,
                    failure_stage=FailureStage.REVIEW_REJECTED,
                    last_error=f"Unexpected: {str(e)}"
                )
        except Exception:
            # task可能不存在（手动复核项），忽略
            pass

        result.final_status = TaskStatus.FAILED
        result.failure_stage = FailureStage.REVIEW_REJECTED
        result.error = f"error: {str(e)}"
        result.record("review_decision", False, result.error)
        return result


def cancel_review(
    ctx: PipelineContext,
    review_id: str,
    reason: str = None,
) -> PipelineResult:
    """D11：取消复核，状态回滚。

    将 review_items.status → 'cancelled'
    回滚 generation_records.review_status → NULL
    回滚 extraction_candidates.review_status → pending
    记录到 review_events 表

    Args:
        ctx: Pipeline上下文
        review_id: 复核项ID
        reason: 取消原因（可选）

    Returns:
        PipelineResult
    """
    from hydro_platform.common.clock import now_iso
    import json
    import uuid

    result = PipelineResult(
        task_id="cancel_review",
        final_status=TaskStatus.SUCCESS,
        reached_stage="cancel_review",
    )

    try:
        # 直接查询 review_items
        review_row = ctx.conn.execute("""
            SELECT review_id, candidate_id, entity_id, status, payload
            FROM review_items
            WHERE review_id = ?
        """, (review_id,)).fetchone()

        if not review_row:
            raise ValueError(f"复核项不存在: {review_id}")

        if review_row['status'] != 'open':
            raise ValueError(f"只能取消状态为open的复核项，当前状态: {review_row['status']}")

        candidate_id = review_row['candidate_id']
        entity_id = review_row['entity_id']

        # 1. 更新 review_items.status → 'cancelled'
        ctx.conn.execute("""
            UPDATE review_items
            SET status = 'cancelled'
            WHERE review_id = ?
        """, (review_id,))

        # 2. 记录到 review_events 表
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        ctx.conn.execute("""
            INSERT INTO review_events
            (event_id, review_id, candidate_id, action, decision, reviewer, reason, created_at)
            VALUES (?, ?, ?, 'cancel', NULL, ?, ?, ?)
        """, (event_id, review_id, candidate_id, ctx.reviewer or 'system', reason, now_iso()))

        # 3. 回滚 extraction_candidates.review_status → pending。
        # v6 将该列设为 NOT NULL；取消不等于已复核，回到待复核状态。
        if candidate_id:
            ctx.conn.execute("""
                UPDATE extraction_candidates
                SET review_status = 'pending'
                WHERE candidate_id = ?
            """, (candidate_id,))

        # 4. 回滚 generation_records.review_status → NULL
        if entity_id and review_row['payload']:
            try:
                payload = json.loads(review_row['payload'])
                cand = payload.get('candidate', {})
                period_label = cand.get('period_label')
                value_type = cand.get('value_type', 'actual')

                if period_label:
                    ctx.conn.execute("""
                        UPDATE generation_records
                        SET review_status = NULL, updated_at = ?
                        WHERE entity_id = ?
                          AND period_label = ?
                          AND value_type = ?
                    """, (now_iso(), entity_id, str(period_label), value_type))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"解析复核payload失败，跳过generation_records回滚: {e}")

        ctx.conn.commit()

        result.record("cancel_review", True, f"cancelled: {reason}" if reason else "cancelled")
        logger.info(f"复核项 {review_id} 已取消")

        return result

    except Exception as e:
        ctx.conn.rollback()
        logger.error(f"取消复核失败: {e}", exc_info=True)
        result.final_status = TaskStatus.FAILED
        result.record("cancel_review", False, str(e))
        return result


# ----- 内部工具 -----

def _ensure_task_active(ctx: PipelineContext, task) -> None:
    """在不可逆写入前读取任务状态，阻止取消任务继续发布。"""
    row = ctx.conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?", (task.task_id,)
    ).fetchone()
    if row is None:
        raise TaskCancelled(f"任务 {task.task_id} 不存在，停止执行")
    status = TaskStatus(row["status"])
    if status is TaskStatus.CANCELLED:
        raise TaskCancelled(f"任务 {task.task_id} 已取消")
    if status is not TaskStatus.RUNNING:
        raise TaskCancelled(f"任务 {task.task_id} 状态为 {status.value}，停止执行")


def _register_source(ctx: PipelineContext, ref, fetched, task) -> str:
    """登记采集快照并回写 Source Registry 的任务适配元数据。"""
    repo = SourceRepository(ctx.conn)
    content_hash = fetched.meta.content_hash if fetched.meta else None
    src_id = SourceRepository.derive_id(ref.url, content_hash)
    src = Source(
        source_id=src_id,
        url=ref.url,
        title=ref.title,
        publisher=ref.publisher,
        content_hash=content_hash,
        archive_path=None,
        language=ref.language,
    ).with_retrieved_now()
    repo.register(src)
    year = _parse_year(task.target_period)
    ctx.conn.execute(
        """
        UPDATE sources
        SET entity_id = ?, entity_type = 'station',
            source_url = COALESCE(source_url, url),
            canonical_url = COALESCE(canonical_url, url),
            source_type = COALESCE(source_type, ?),
            document_type = COALESCE(document_type, ?),
            covered_metric = COALESCE(covered_metric, 'generation'),
            covered_year = COALESCE(covered_year, ?),
            source_reliability_score = COALESCE(source_reliability_score, 0.5),
            success_count = COALESCE(success_count, 0),
            failure_count = COALESCE(failure_count, 0),
            updated_at = ?
        WHERE source_id = ?
        """,
        (
            task.entity_id,
            "manual" if getattr(task, "source_type", None) == "manual" else "collected",
            getattr(ref, "expected", None) or "unknown",
            year,
            now_iso(),
            src_id,
        ),
    )
    return src_id


def _candidate_id(cand, document_id: str) -> str:
    """为已归档文档中的候选生成稳定 ID，保证失败重跑可幂等续跑。"""
    payload = cand.model_dump(mode="json", exclude={"candidate_id"})
    payload["document_id"] = document_id
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "cand_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _promote(ctx, result, cand, val, eid, *, review_required: bool) -> None:
    """提升候选值到正式库。

    P0-6修复：失败时抛出 PipelineError，不再静默返回。
    """
    from ..lifecycle.promotion import PromotionError, promote_candidate

    try:
        pr = promote_candidate(
            ctx.conn, cand, val,
            evidence_id=eid, review_approved=True, review_required=review_required,
        )
    except PromotionError as exc:
        # P0-6关键修复：抛出异常而不是静默返回
        logger.error(f"候选升级失败: {exc}")
        raise PipelineError(
            FailureStage.DATABASE_WRITE_FAILED,
            f"Promotion failed: {str(exc)}",
            cause=exc
        )

    result.candidates_promoted += 1
    result.promoted_keys.append(
        {
            "entity_id": pr.entity_id,
            "period_label": pr.period_label,
            "value_type": pr.value_type,
            "newly_created": pr.newly_created,
        }
    )



def _rebuild_from_review(ctx, row, task=None):
    """从 review_items.payload 重建候选 + 校验 + evidence_id。

    重跑校验时携带与首次一致的上下文（装机容量、期望年份），避免漏掉依赖上下文的
    HIGH 级检查（容量上限、年份不符）——否则人工 approve 后可能放行本应硬阻断者。
    """
    import json

    from ..models.candidate import ExtractionCandidate

    payload = json.loads(row["payload"]) if row["payload"] else {}
    cand = ExtractionCandidate.model_validate(payload["candidate"])
    # 历史手工/CSV 复核项的 payload 可能早于 task_id 绑定。决策路径传入的
    # 已持久化任务是唯一权威，确保升级后的正式事实也能回溯到该任务。
    if task is not None:
        cand.task_id = task.task_id
    vctx = ValidationContext()
    entity_id = task.entity_id if task is not None else cand.entity_id
    if entity_id:
        capacity_mw, _ = _entity_facts(ctx, entity_id)
        vctx.entity_capacity_mw = capacity_mw
    if task is not None:
        vctx.expected_year = _parse_year(task.target_period)
    val = validate_candidate(cand, vctx)  # 重跑校验，确保仍无硬阻断
    evidence_ids = payload.get("evidence_ids") or []
    eid = evidence_ids[0] if evidence_ids else ""
    return cand, val, eid


def _llm_candidates(ctx, parsed, task, src_id):
    from ..extraction.llm.extractor import llm_extract

    return llm_extract(
        parsed.text,
        ctx.llm_provider,
        entity_id=task.entity_id,
        target_period=task.target_period,
        task_id=task.task_id,
        source_id=src_id,
        locator="llm",
    )


def _parse_year(period: str | None) -> int | None:
    if not period:
        return None
    import re

    m = re.search(r"(19|20)\d{2}", period)
    return int(m.group(0)) if m else None


def _fail(tm, result, stage: FailureStage, message: str) -> PipelineResult:
    tm.mark_failed(result.task_id, failure_stage=stage, last_error=message)
    result.final_status = TaskStatus.FAILED
    result.failure_stage = stage
    result.error = message
    result.record(stage.value, False, message)
    logger.info("任务 %s 失败于 %s：%s", result.task_id, stage.value, message)
    return result
