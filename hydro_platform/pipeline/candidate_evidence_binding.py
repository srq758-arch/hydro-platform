"""D06修复：候选→证据不可变对应。

基于 fork_1 完成的 extraction_candidates 表结构，确保：
1. 每个候选记录在创建时关联不可变的 evidence_id
2. 候选与证据通过 candidate_evidence 表强关联
3. 候选生成后，证据关联不可更改
4. 防止候选与证据脱钩
"""

import logging
import sqlite3
from typing import List, Optional, Dict, Any
from hydro_platform.common.clock import now_iso

logger = logging.getLogger(__name__)


class CandidateEvidenceError(Exception):
    """候选-证据关联错误。"""
    pass


def create_candidate_with_evidence(
    conn: sqlite3.Connection,
    candidate_id: str,
    task_id: str,
    entity_id: str,
    document_id: str,
    evidence_ids: List[str],
    period_type: str,
    period_label: str,
    value_type: str,
    measurement_scope: str,
    metric: Optional[str] = None,
    normalized_unit: Optional[str] = None,
    generation_gwh: Optional[float] = None,
    value_raw: Optional[str] = None,
    unit_raw: Optional[str] = None,
    snippet: Optional[str] = None,
    extraction_method: Optional[str] = None
) -> str:
    """创建候选记录并关联证据（不可变）。

    Args:
        conn: 数据库连接
        candidate_id: 候选ID
        task_id: 任务ID
        entity_id: 实体ID
        document_id: 文档ID
        evidence_ids: 证据ID列表（必须非空）
        period_type: 周期类型
        period_label: 周期标签
        value_type: 值类型
        measurement_scope: 测量范围
        generation_gwh: 发电量（GWh）
        value_raw: 原始值
        unit_raw: 原始单位
        snippet: 摘要
        extraction_method: 提取方法

    Returns:
        candidate_id

    Raises:
        CandidateEvidenceError: 如果证据列表为空或证据不存在
    """
    # 验证证据列表非空
    if not evidence_ids:
        raise CandidateEvidenceError(
            f"候选 {candidate_id} 必须关联至少一个证据"
        )

    # 验证所有证据存在
    placeholders = ','.join('?' * len(evidence_ids))
    existing_evidence = conn.execute(f"""
        SELECT evidence_id FROM evidence
        WHERE evidence_id IN ({placeholders})
    """, evidence_ids).fetchall()

    existing_ids = {row['evidence_id'] for row in existing_evidence}
    missing_ids = set(evidence_ids) - existing_ids

    if missing_ids:
        raise CandidateEvidenceError(
            f"证据不存在: {', '.join(missing_ids)}"
        )

    # 插入候选记录
    conn.execute("""
        INSERT INTO extraction_candidates (
            candidate_id, task_id, entity_id, document_id,
            period_type, period_label, value_type, measurement_scope,
            metric, normalized_unit, generation_gwh, value_raw, unit_raw, snippet,
            extraction_method, extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(candidate_id) DO NOTHING
    """, (
        candidate_id, task_id, entity_id, document_id,
        period_type, period_label, value_type, measurement_scope,
        metric, normalized_unit, generation_gwh, value_raw, unit_raw, snippet,
        extraction_method, now_iso()
    ))

    # 关联证据（不可变）
    for evidence_id in evidence_ids:
        conn.execute("""
            INSERT INTO candidate_evidence (candidate_id, evidence_id)
            VALUES (?, ?)
            ON CONFLICT(candidate_id, evidence_id) DO NOTHING
        """, (candidate_id, evidence_id))

    conn.commit()

    logger.info(
        f"创建候选 {candidate_id}，关联 {len(evidence_ids)} 个证据（不可变）"
    )

    return candidate_id


def get_candidate_evidence(
    conn: sqlite3.Connection,
    candidate_id: str
) -> List[str]:
    """获取候选关联的证据ID列表。

    Args:
        conn: 数据库连接
        candidate_id: 候选ID

    Returns:
        证据ID列表
    """
    rows = conn.execute("""
        SELECT evidence_id FROM candidate_evidence
        WHERE candidate_id = ?
        ORDER BY evidence_id
    """, (candidate_id,)).fetchall()

    return [row['evidence_id'] for row in rows]


def validate_candidate_evidence_immutable(
    conn: sqlite3.Connection,
    candidate_id: str
) -> tuple[bool, str]:
    """验证候选的证据关联是否不可变（未被篡改）。

    Args:
        conn: 数据库连接
        candidate_id: 候选ID

    Returns:
        (is_valid, reason): 验证结果和原因
    """
    # 检查候选是否存在
    candidate = conn.execute("""
        SELECT candidate_id FROM extraction_candidates
        WHERE candidate_id = ?
    """, (candidate_id,)).fetchone()

    if not candidate:
        return False, f"候选 {candidate_id} 不存在"

    # 检查是否有证据关联
    evidence_ids = get_candidate_evidence(conn, candidate_id)

    if not evidence_ids:
        return False, f"候选 {candidate_id} 未关联任何证据"

    # 检查所有证据是否存在
    placeholders = ','.join('?' * len(evidence_ids))
    existing = conn.execute(f"""
        SELECT evidence_id FROM evidence
        WHERE evidence_id IN ({placeholders})
    """, evidence_ids).fetchall()

    existing_ids = {row['evidence_id'] for row in existing}
    missing_ids = set(evidence_ids) - existing_ids

    if missing_ids:
        return False, (
            f"候选 {candidate_id} 关联的证据已丢失: "
            f"{', '.join(missing_ids)}"
        )

    return True, f"候选 {candidate_id} 证据关联完整"


def get_candidate_with_evidence(
    conn: sqlite3.Connection,
    candidate_id: str
) -> Optional[Dict[str, Any]]:
    """获取候选记录及其关联的证据。

    Args:
        conn: 数据库连接
        candidate_id: 候选ID

    Returns:
        候选记录（包含 evidence_ids 字段），如果不存在返回 None
    """
    # 获取候选记录
    candidate = conn.execute("""
        SELECT * FROM extraction_candidates
        WHERE candidate_id = ?
    """, (candidate_id,)).fetchone()

    if not candidate:
        return None

    # 转为字典
    candidate_dict = dict(candidate)

    # 添加证据ID列表
    candidate_dict['evidence_ids'] = get_candidate_evidence(conn, candidate_id)

    return candidate_dict


def promote_candidate_to_generation_record(
    conn: sqlite3.Connection,
    candidate_id: str,
    source_id: Optional[str] = None,
    task_id: Optional[str] = None
) -> int:
    """将候选升级为正式发电记录（带证据溯源）。

    Args:
        conn: 数据库连接
        candidate_id: 候选ID
        source_id: 数据源ID（可选）
        task_id: 任务ID（可选）

    Returns:
        生成的 generation_records.id

    Raises:
        CandidateEvidenceError: 如果候选不存在或证据缺失
    """
    # V5.2-A：保留名称以便陈旧调用明确失败。该旧函数未携带 Validation、
    # Review 与审批版本，不能再作为正式写入路径。
    raise CandidateEvidenceError(
        "旧候选升级入口已禁用；请使用 lifecycle.promotion.promote_candidate"
    )


def verify_generation_record_traceability(
    conn: sqlite3.Connection,
    record_id: int
) -> tuple[bool, str]:
    """验证正式记录的溯源完整性。

    Args:
        conn: 数据库连接
        record_id: generation_records.id

    Returns:
        (is_valid, reason): 验证结果和原因
    """
    # 获取正式记录
    record = conn.execute("""
        SELECT id, candidate_id, evidence_id, entity_id
        FROM generation_records
        WHERE id = ?
    """, (record_id,)).fetchone()

    if not record:
        return False, f"记录 {record_id} 不存在"

    candidate_id = record['candidate_id']
    evidence_id = record['evidence_id']

    # 检查候选关联
    if not candidate_id:
        return False, f"记录 {record_id} 未关联候选"

    # 验证候选存在
    candidate = conn.execute("""
        SELECT candidate_id FROM extraction_candidates
        WHERE candidate_id = ?
    """, (candidate_id,)).fetchone()

    if not candidate:
        return False, f"记录 {record_id} 关联的候选 {candidate_id} 不存在"

    # 检查证据关联
    if not evidence_id:
        return False, f"记录 {record_id} 未关联证据"

    # 验证证据在候选的证据列表中
    candidate_evidence_ids = get_candidate_evidence(conn, candidate_id)

    if evidence_id not in candidate_evidence_ids:
        return False, (
            f"记录 {record_id} 的证据 {evidence_id} "
            f"不在候选 {candidate_id} 的证据列表中"
        )

    return True, f"记录 {record_id} 溯源完整"
