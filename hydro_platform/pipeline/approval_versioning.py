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
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def compute_candidate_hash(candidate_data: Dict[str, Any]) -> str:
    """计算候选数据的内容哈希。

    Args:
        candidate_data: 候选数据字典

    Returns:
        SHA256 哈希值（16进制字符串）
    """
    # 提取关键字段用于哈希计算
    # 排除不影响数据本质的字段（如创建时间、ID等）
    key_fields = {
        'entity_id': candidate_data.get('entity_id'),
        'period_label': candidate_data.get('period_label'),
        'generation_gwh': candidate_data.get('generation_gwh'),
        'value_type': candidate_data.get('value_type'),
        'source_id': candidate_data.get('source_id'),
        'evidence_id': candidate_data.get('evidence_id'),
        # 可以添加其他关键字段
    }

    # 移除 None 值
    key_fields = {k: v for k, v in key_fields.items() if v is not None}

    # 按键排序后序列化（确保哈希稳定）
    canonical_json = json.dumps(key_fields, sort_keys=True, ensure_ascii=False)

    # 计算 SHA256 哈希
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


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

    if invalidated_count > 0:
        conn.commit()

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
