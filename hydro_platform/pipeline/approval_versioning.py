"""D07修复：防止旧审批复用。

问题：
- 相同 entity_id + period 的新候选可能错误复用旧审批
- 候选数据变化后（如来源、数值变化），旧审批应失效
- 当前系统仅基于 (entity_id, fact_type, fact_key) 查找审批

解决方案：
- 审批应绑定候选内容的哈希值
- 候选变化时，内容哈希改变，旧审批不再匹配
- 提供审批失效检测和清理机制
"""

import hashlib
import json
import logging
import sqlite3
from typing import Optional, Dict, Any, Iterable

logger = logging.getLogger(__name__)


_CANDIDATE_HASH_FIELDS = (
    "entity_id",
    "period_type",
    "period_label",
    "generation_gwh",
    "value_type",
    "measurement_scope",
    "metric",
    "normalized_unit",
    "value_raw",
    "unit_raw",
    "snippet",
    "locator",
    "extractor",
    "extraction_method",
    "source_id",
    "document_id",
)


def _json_value(value: Any) -> Any:
    """Return a stable JSON value for Pydantic enums and ordinary scalars."""
    return value.value if hasattr(value, "value") else value


def compute_candidate_hash(candidate_data: Dict[str, Any]) -> str:
    """计算候选数据的内容哈希。

    Args:
        candidate_data: 候选数据字典

    Returns:
        SHA256 哈希值（16进制字符串）
    """
    # 审批必须绑定完整事实语义以及证据/文档版本。时间戳和数据库行号等
    # 非业务字段不参与哈希，避免无意义的审批失效。
    key_fields = {
        field: _json_value(candidate_data.get(field))
        for field in _CANDIDATE_HASH_FIELDS
        if candidate_data.get(field) is not None
    }
    if candidate_data.get("evidence_id") is not None:
        key_fields["evidence_id"] = candidate_data["evidence_id"]
    if candidate_data.get("evidence_ids") is not None:
        key_fields["evidence_ids"] = sorted(candidate_data["evidence_ids"])
    if candidate_data.get("evidence_versions") is not None:
        key_fields["evidence_versions"] = sorted(
            candidate_data["evidence_versions"],
            key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
        )

    # 按键排序后序列化（确保哈希稳定）
    canonical_json = json.dumps(key_fields, sort_keys=True, ensure_ascii=False)

    # 计算 SHA256 哈希
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


def load_persisted_candidate_approval_data(
    conn: sqlite3.Connection,
    candidate_id: str,
    *,
    expected_evidence_ids: Iterable[str] | None = None,
) -> Dict[str, Any]:
    """Load the immutable candidate/evidence/document chain used by approval.

    The hash is deliberately rebuilt from persisted rows rather than the review
    payload.  This makes an approval fail closed if a candidate, its evidence,
    or the archived document version changes after the item entered the queue.
    """
    candidate = conn.execute(
        "SELECT * FROM extraction_candidates WHERE candidate_id = ?",
        (candidate_id,),
    ).fetchone()
    if candidate is None:
        raise ValueError(f"候选不存在: {candidate_id}")

    data = dict(candidate)
    expected = sorted(set(expected_evidence_ids or []))
    linked_rows = conn.execute(
        """
        SELECT ce.evidence_id,
               e.source_id, e.document_id, e.content_hash,
               e.fact_type, e.fact_key, e.source_url, e.final_url,
               e.page_number, e.table_reference, e.section_title,
               e.snippet, e.locator, e.parser_version, e.extraction_version,
               d.original_url AS document_url,
               d.content_hash AS document_content_hash,
               d.version AS document_version
        FROM candidate_evidence ce
        LEFT JOIN evidence e ON e.evidence_id = ce.evidence_id
        LEFT JOIN documents d ON d.document_id = e.document_id
        WHERE ce.candidate_id = ?
        ORDER BY ce.evidence_id
        """,
        (candidate_id,),
    ).fetchall()
    linked_ids = [row["evidence_id"] for row in linked_rows]
    if not linked_ids:
        raise ValueError(f"候选未关联证据: {candidate_id}")
    if expected and linked_ids != expected:
        raise ValueError(
            f"候选证据集合与复核载荷不一致: expected={expected}, actual={linked_ids}"
        )

    evidence_versions = []
    for row in linked_rows:
        version = dict(row)
        if version.get("document_id") is None or version.get("content_hash") is None:
            raise ValueError(f"证据链不完整: {row['evidence_id']}")
        if version.get("document_content_hash") != version.get("content_hash"):
            raise ValueError(f"证据与归档文档内容哈希不一致: {row['evidence_id']}")
        evidence_versions.append(version)

    data["evidence_ids"] = linked_ids
    data["evidence_versions"] = evidence_versions
    return data


def compute_persisted_candidate_hash(
    conn: sqlite3.Connection,
    candidate_id: str,
    *,
    expected_evidence_ids: Iterable[str] | None = None,
) -> str:
    """Compute the approval hash from the current persisted evidence chain."""
    return compute_candidate_hash(
        load_persisted_candidate_approval_data(
            conn,
            candidate_id,
            expected_evidence_ids=expected_evidence_ids,
        )
    )


def add_candidate_hash_to_review(
    conn: sqlite3.Connection,
    review_id: str,
    candidate_hash: str
) -> None:
    """将候选内容哈希添加到复核记录。

    Args:
        conn: 数据库连接
        review_id: 复核项ID
        candidate_hash: 候选内容哈希
    """
    # 更新 review_items 的 payload，添加 candidate_hash 字段
    review = conn.execute("""
        SELECT payload FROM review_items WHERE review_id = ?
    """, (review_id,)).fetchone()

    if not review:
        logger.warning(f"复核项 {review_id} 不存在")
        return

    payload = json.loads(review['payload'] or '{}')
    payload['candidate_hash'] = candidate_hash

    conn.execute("""
        UPDATE review_items
        SET payload = ?
        WHERE review_id = ?
    """, (json.dumps(payload), review_id))


def check_approval_reuse(
    conn: sqlite3.Connection,
    entity_id: str,
    fact_type: str,
    fact_key: str,
    new_candidate_hash: str
) -> tuple[bool, Optional[str]]:
    """检查是否存在可复用的审批（基于内容哈希）。

    Args:
        conn: 数据库连接
        entity_id: 实体ID
        fact_type: 事实类型
        fact_key: 事实键
        new_candidate_hash: 新候选的内容哈希

    Returns:
        (can_reuse, old_review_id): 是否可复用，以及旧审批ID
    """
    # 查找相同 entity_id + fact_type + fact_key 的已审批项
    old_reviews = conn.execute("""
        SELECT review_id, payload, status
        FROM review_items
        WHERE entity_id = ?
          AND fact_type = ?
          AND fact_key = ?
          AND status = 'approved'
        ORDER BY resolved_at DESC
        LIMIT 1
    """, (entity_id, fact_type, fact_key)).fetchall()

    if not old_reviews:
        return False, None

    old_review = old_reviews[0]
    old_payload = json.loads(old_review['payload'] or '{}')
    old_hash = old_payload.get('candidate_hash')

    if not old_hash:
        # 旧审批没有哈希，无法判断，建议不复用
        logger.warning(
            f"旧审批 {old_review['review_id']} 缺少 candidate_hash，"
            f"建议重新复核"
        )
        return False, old_review['review_id']

    # 比较哈希值
    if old_hash == new_candidate_hash:
        logger.info(
            f"候选内容未变化（hash={new_candidate_hash[:8]}...），"
            f"可复用审批 {old_review['review_id']}"
        )
        return True, old_review['review_id']
    else:
        logger.info(
            f"候选内容已变化（旧={old_hash[:8]}... vs 新={new_candidate_hash[:8]}...），"
            f"旧审批 {old_review['review_id']} 不可复用"
        )
        return False, old_review['review_id']


def invalidate_stale_approvals(
    conn: sqlite3.Connection,
    entity_id: str,
    fact_type: str,
    fact_key: str,
    new_candidate_hash: str
) -> int:
    """使过期的审批失效。

    Args:
        conn: 数据库连接
        entity_id: 实体ID
        fact_type: 事实类型
        fact_key: 事实键
        new_candidate_hash: 新候选的内容哈希

    Returns:
        失效的审批数量
    """
    # 查找所有相关的已审批项
    old_reviews = conn.execute("""
        SELECT review_id, payload
        FROM review_items
        WHERE entity_id = ?
          AND fact_type = ?
          AND fact_key = ?
          AND status = 'approved'
    """, (entity_id, fact_type, fact_key)).fetchall()

    invalidated_count = 0

    for review in old_reviews:
        payload = json.loads(review['payload'] or '{}')
        old_hash = payload.get('candidate_hash')

        # 如果哈希不匹配，标记为失效
        if old_hash and old_hash != new_candidate_hash:
            conn.execute("""
                UPDATE review_items
                SET status = 'invalidated'
                WHERE review_id = ?
            """, (review['review_id'],))
            invalidated_count += 1
            logger.info(f"审批 {review['review_id']} 因候选变化而失效")

    return invalidated_count


def create_review_with_hash(
    conn: sqlite3.Connection,
    review_id: str,
    entity_id: str,
    fact_type: str,
    fact_key: str,
    reason: str,
    candidate_data: Dict[str, Any],
    task_id: Optional[str] = None
) -> str:
    """创建复核项并自动计算候选哈希。

    Args:
        conn: 数据库连接
        review_id: 复核项ID
        entity_id: 实体ID
        fact_type: 事实类型
        fact_key: 事实键
        reason: 复核原因
        candidate_data: 候选数据
        task_id: 任务ID（可选）

    Returns:
        候选内容哈希
    """
    from hydro_platform.common.clock import now_iso

    # 计算候选哈希
    candidate_hash = compute_candidate_hash(candidate_data)

    # 构建 payload
    payload = {
        'candidate': candidate_data,
        'candidate_hash': candidate_hash
    }

    # 插入复核项
    conn.execute("""
        INSERT INTO review_items (
            review_id, entity_id, fact_type, fact_key,
            reason, status, payload, task_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        review_id, entity_id, fact_type, fact_key,
        reason, 'open', json.dumps(payload), task_id, now_iso()
    ))

    logger.info(
        f"创建复核项 {review_id}，候选哈希={candidate_hash[:8]}..."
    )

    return candidate_hash


def should_create_new_review(
    conn: sqlite3.Connection,
    entity_id: str,
    fact_type: str,
    fact_key: str,
    new_candidate_data: Dict[str, Any]
) -> tuple[bool, str]:
    """判断是否需要创建新的复核项。

    Args:
        conn: 数据库连接
        entity_id: 实体ID
        fact_type: 事实类型
        fact_key: 事实键
        new_candidate_data: 新候选数据

    Returns:
        (should_create, reason): 是否需要创建，以及原因
    """
    # 计算新候选的哈希
    new_hash = compute_candidate_hash(new_candidate_data)

    # 检查是否可复用旧审批
    can_reuse, old_review_id = check_approval_reuse(
        conn=conn,
        entity_id=entity_id,
        fact_type=fact_type,
        fact_key=fact_key,
        new_candidate_hash=new_hash
    )

    if can_reuse:
        return False, f"可复用审批 {old_review_id}，候选内容未变化"
    else:
        if old_review_id:
            return True, f"候选内容已变化，旧审批 {old_review_id} 不可复用"
        else:
            return True, "无旧审批，需要新建复核项"
