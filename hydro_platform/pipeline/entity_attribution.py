"""实体归属验证模块（D05修复）。

防止 entity_id 误判，例如：
- 美国电站被识别为中国电站
- 数据源明确指向实体A，但被关联到实体B

在候选生成阶段验证实体归属的合理性。
"""

import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)


class EntityAttributionError(Exception):
    """实体归属验证失败异常。"""
    pass


def validate_entity_attribution(
    conn: sqlite3.Connection,
    entity_id: str,
    source_country: Optional[str] = None,
    source_text: Optional[str] = None,
    evidence_snippet: Optional[str] = None
) -> tuple[bool, str]:
    """验证实体归属的合理性。

    Args:
        conn: 数据库连接
        entity_id: 待验证的实体ID
        source_country: 数据源所属国家（可选）
        source_text: 原始文本片段（可选）
        evidence_snippet: 证据摘要（可选）

    Returns:
        (is_valid, reason): 验证结果和原因
    """
    # 查询实体基本信息
    entity = conn.execute("""
        SELECT entity_id, canonical_name, country, region
        FROM stations
        WHERE entity_id = ?
    """, (entity_id,)).fetchone()

    if not entity:
        return False, f"实体 {entity_id} 不存在于 stations 表"

    entity_country = entity['country']
    entity_name = entity['canonical_name']

    # 规则1: 数据源国家与实体国家不匹配
    if source_country and source_country != entity_country:
        # 特例：某些国际数据源（如世界银行）可以覆盖多国
        # 但如果明确是单一国家的数据源，则必须匹配
        if source_country in ['US', 'CN', 'BR', 'CA', 'IN']:  # 主要数据生产国
            return False, (
                f"国家不匹配: 数据源={source_country}, "
                f"实体={entity_country} ({entity_name})"
            )

    # 规则2: 文本中包含明显的国家标识
    if source_text or evidence_snippet:
        text = (source_text or '') + ' ' + (evidence_snippet or '')
        text = text.lower()

        # 美国标识
        us_markers = ['united states', 'u.s.', 'usa', 'american', 'eia-']
        # 中国标识
        cn_markers = ['china', 'chinese', '中国', '中华', 'prc']
        # 巴西标识
        br_markers = ['brazil', 'brazilian', 'brasil']

        has_us = any(marker in text for marker in us_markers)
        has_cn = any(marker in text for marker in cn_markers)
        has_br = any(marker in text for marker in br_markers)

        # 如果实体是美国的，但文本明确指向中国
        if entity_country == 'US' and has_cn and not has_us:
            return False, (
                f"文本指向中国，但实体是美国: {entity_name} ({entity_id})"
            )

        # 如果实体是中国的，但文本明确指向美国
        if entity_country == 'CN' and has_us and not has_cn:
            return False, (
                f"文本指向美国，但实体是中国: {entity_name} ({entity_id})"
            )

        # 如果实体是巴西的，但文本明确指向其他国家
        if entity_country == 'BR' and (has_us or has_cn) and not has_br:
            return False, (
                f"文本指向其他国家，但实体是巴西: {entity_name} ({entity_id})"
            )

    # 规则3: 实体名称在文本中的匹配度检查（可选，较宽松）
    # 如果提供了文本，但实体名称完全不出现，给出警告（不拒绝）
    if (source_text or evidence_snippet) and entity_name:
        text = (source_text or '') + ' ' + (evidence_snippet or '')
        # 取实体名称的前3个单词或前20个字符作为关键部分
        name_parts = entity_name.split()[:3]
        name_key = ' '.join(name_parts) if name_parts else entity_name[:20]

        if name_key.lower() not in text.lower():
            logger.warning(
                f"实体名称 '{name_key}' 未出现在文本中，可能存在归属问题"
            )
            # 不拒绝，只警告

    return True, "实体归属验证通过"


def validate_candidate_attribution(
    conn: sqlite3.Connection,
    entity_id: str,
    source_id: str,
    evidence_id: Optional[str] = None
) -> tuple[bool, str]:
    """验证候选数据的实体归属（基于数据库记录）。

    Args:
        conn: 数据库连接
        entity_id: 候选关联的实体ID
        source_id: 数据源ID
        evidence_id: 证据ID（可选）

    Returns:
        (is_valid, reason): 验证结果和原因
    """
    # 查询数据源信息
    source = conn.execute("""
        SELECT source_id, url, title, publisher
        FROM sources
        WHERE source_id = ?
    """, (source_id,)).fetchone()

    if not source:
        return False, f"数据源 {source_id} 不存在"

    source_url = source['url'] or ''
    source_title = source['title'] or ''

    # 从URL推断国家
    source_country = None
    if 'eia.gov' in source_url:
        source_country = 'US'
    elif 'stats.gov.cn' in source_url or '.cn/' in source_url:
        source_country = 'CN'
    elif '.gov.br' in source_url or 'aneel.gov.br' in source_url:
        source_country = 'BR'

    # 查询证据摘要（如果提供）
    evidence_snippet = None
    if evidence_id:
        evidence = conn.execute("""
            SELECT snippet, source_url
            FROM evidence
            WHERE evidence_id = ?
        """, (evidence_id,)).fetchone()

        if evidence:
            evidence_snippet = evidence['snippet']
            # 如果证据有不同的URL，也检查
            if evidence['source_url'] and evidence['source_url'] != source_url:
                if 'eia.gov' in evidence['source_url']:
                    source_country = 'US'

    # 执行归属验证
    return validate_entity_attribution(
        conn=conn,
        entity_id=entity_id,
        source_country=source_country,
        source_text=source_title,
        evidence_snippet=evidence_snippet
    )


def check_and_log_attribution(
    conn: sqlite3.Connection,
    entity_id: str,
    source_id: str,
    evidence_id: Optional[str] = None,
    raise_on_failure: bool = False
) -> bool:
    """检查实体归属并记录日志。

    Args:
        conn: 数据库连接
        entity_id: 实体ID
        source_id: 数据源ID
        evidence_id: 证据ID（可选）
        raise_on_failure: 验证失败时是否抛出异常

    Returns:
        验证是否通过

    Raises:
        EntityAttributionError: 如果 raise_on_failure=True 且验证失败
    """
    is_valid, reason = validate_candidate_attribution(
        conn=conn,
        entity_id=entity_id,
        source_id=source_id,
        evidence_id=evidence_id
    )

    if is_valid:
        logger.info(f"实体归属验证通过: {entity_id} <- {source_id}")
        return True
    else:
        logger.error(f"实体归属验证失败: {reason}")

        if raise_on_failure:
            raise EntityAttributionError(reason)

        return False
