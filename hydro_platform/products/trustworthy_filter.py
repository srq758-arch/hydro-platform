"""可信数据过滤器：统一所有排名、导出、展示的过滤规则。

D04修复：确保所有入口（桌面Top100、Products排名、数据库视图、导出）
使用相同的可信标准，防止不合格数据泄漏到任何展示渠道。

可信数据的完整标准（规划第15、20节）：
1. value_type = 'actual'（实际值，非预测或估算）
2. period_type = 'calendar_year'（日历年，非财年或季度）
3. measurement_scope = 'plant'（单站，非群组或区域合计）
4. validation_status = 'passed'（校验通过）
5. publication_status = 'publishable'（可发布）
6. review_status = 'approved'（已批准）
7. evidence_id 对应真实 Evidence，且 Candidate→Evidence→Document 链路完整
8. confidence >= 0.7（置信度阈值，可配置）
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List
import sqlite3


class TrustworthyFilter:
    """统一可信数据过滤器。"""

    # 默认置信度阈值
    DEFAULT_CONFIDENCE_THRESHOLD = 0.7

    @staticmethod
    def get_sql_where_clause(
        *,
        year: Optional[str] = None,
        country: Optional[str] = None,
        confidence_threshold: Optional[float] = None,
        table_alias: str = "g"
    ) -> tuple[str, list]:
        """生成可信数据的 SQL WHERE 子句。

        Args:
            year: 可选年份过滤
            country: 可选国家过滤
            confidence_threshold: 置信度阈值，默认0.7
            table_alias: generation_records表的别名

        Returns:
            (where_clause, params) 元组
        """
        if confidence_threshold is None:
            confidence_threshold = TrustworthyFilter.DEFAULT_CONFIDENCE_THRESHOLD

        conditions = [
            # 核心可信标准
            f"{table_alias}.value_type = ?",
            f"{table_alias}.period_type = ?",
            f"{table_alias}.measurement_scope = ?",
            f"{table_alias}.validation_status = ?",
            f"{table_alias}.publication_status = ?",
            f"{table_alias}.review_status = ?",
            f"{table_alias}.evidence_id IS NOT NULL",
            f"({table_alias}.confidence IS NULL OR {table_alias}.confidence >= ?)",
        ]

        params = [
            'actual',           # value_type
            'calendar_year',    # period_type
            'plant',            # measurement_scope
            'passed',           # validation_status
            'publishable',      # publication_status
            'approved',         # review_status
            confidence_threshold
        ]

        # 可选过滤条件
        if year:
            conditions.append(f"{table_alias}.period_label = ?")
            params.append(str(year))

        if country:
            # 需要 JOIN stations 表
            conditions.append("s.country = ?")
            params.append(country)

        where_clause = " AND ".join(conditions)
        return where_clause, params

    @staticmethod
    def filter_records(
        conn: sqlite3.Connection,
        *,
        year: Optional[str] = None,
        country: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        confidence_threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """查询可信发电量记录。

        Args:
            conn: 数据库连接
            year: 可选年份
            country: 可选国家
            limit: 返回数量限制
            offset: 偏移量
            confidence_threshold: 置信度阈值

        Returns:
            可信记录列表
        """
        where_clause, params = TrustworthyFilter.get_sql_where_clause(
            year=year,
            country=country,
            confidence_threshold=confidence_threshold,
            table_alias="g"
        )

        query = f"""
            SELECT
                g.id,
                g.entity_id,
                s.canonical_name,
                s.country,
                g.period_label AS year,
                g.generation_gwh,
                g.confidence,
                g.value_raw,
                g.unit_raw,
                g.evidence_id,
                g.validation_status,
                g.review_status,
                g.publication_status
            FROM generation_records g
            JOIN stations s ON g.entity_id = s.entity_id
            JOIN extraction_candidates c
              ON c.candidate_id = g.candidate_id
             AND c.entity_id = g.entity_id
             AND c.period_type = g.period_type
             AND c.period_label = g.period_label
             AND c.value_type = g.value_type
             AND c.measurement_scope = g.measurement_scope
             AND c.generation_gwh = g.generation_gwh
            JOIN candidate_evidence ce
              ON ce.candidate_id = c.candidate_id AND ce.evidence_id = g.evidence_id
            JOIN evidence e ON e.evidence_id = g.evidence_id
            JOIN documents d
              ON d.document_id = c.document_id
             AND d.document_id = e.document_id
             AND d.content_hash = e.content_hash
            WHERE {where_clause}
            ORDER BY g.generation_gwh DESC
            LIMIT ? OFFSET ?
        """

        rows = conn.execute(query, params + [limit, offset]).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def count_trustworthy_records(
        conn: sqlite3.Connection,
        *,
        year: Optional[str] = None,
        country: Optional[str] = None,
        confidence_threshold: Optional[float] = None
    ) -> int:
        """统计符合可信标准的记录数量。

        Args:
            conn: 数据库连接
            year: 可选年份
            country: 可选国家
            confidence_threshold: 置信度阈值

        Returns:
            可信记录总数
        """
        where_clause, params = TrustworthyFilter.get_sql_where_clause(
            year=year,
            country=country,
            confidence_threshold=confidence_threshold,
            table_alias="g"
        )

        query = f"""
            SELECT COUNT(*) as total
            FROM generation_records g
            JOIN stations s ON g.entity_id = s.entity_id
            JOIN extraction_candidates c
              ON c.candidate_id = g.candidate_id
             AND c.entity_id = g.entity_id
             AND c.period_type = g.period_type
             AND c.period_label = g.period_label
             AND c.value_type = g.value_type
             AND c.measurement_scope = g.measurement_scope
             AND c.generation_gwh = g.generation_gwh
            JOIN candidate_evidence ce
              ON ce.candidate_id = c.candidate_id AND ce.evidence_id = g.evidence_id
            JOIN evidence e ON e.evidence_id = g.evidence_id
            JOIN documents d
              ON d.document_id = c.document_id
             AND d.document_id = e.document_id
             AND d.content_hash = e.content_hash
            WHERE {where_clause}
        """

        result = conn.execute(query, params).fetchone()
        return result['total'] if result else 0

    @staticmethod
    def validate_record_trustworthy(record: Dict[str, Any]) -> tuple[bool, list[str]]:
        """验证单条记录是否符合可信标准。

        Args:
            record: 记录字典，必须包含所有相关字段

        Returns:
            (is_trustworthy, violation_reasons) 元组
        """
        violations = []

        # 检查各项标准
        if record.get('value_type') != 'actual':
            violations.append(f"value_type={record.get('value_type')}，非actual")

        if record.get('period_type') != 'calendar_year':
            violations.append(f"period_type={record.get('period_type')}，非calendar_year")

        if record.get('measurement_scope') != 'plant':
            violations.append(f"measurement_scope={record.get('measurement_scope')}，非plant")

        if record.get('validation_status') != 'passed':
            violations.append(f"validation_status={record.get('validation_status')}，未通过校验")

        if record.get('publication_status') != 'publishable':
            violations.append(f"publication_status={record.get('publication_status')}，不可发布")

        if record.get('review_status') != 'approved':
            violations.append(f"review_status={record.get('review_status')}，未批准")

        if not record.get('evidence_id'):
            violations.append("缺少evidence_id")

        confidence = record.get('confidence')
        if confidence is not None and confidence < TrustworthyFilter.DEFAULT_CONFIDENCE_THRESHOLD:
            violations.append(f"confidence={confidence}，低于阈值{TrustworthyFilter.DEFAULT_CONFIDENCE_THRESHOLD}")

        is_trustworthy = len(violations) == 0
        return is_trustworthy, violations


def get_top_n_trustworthy(
    conn: sqlite3.Connection,
    year: str,
    n: int = 100,
    country: Optional[str] = None,
    confidence_threshold: Optional[float] = None
) -> List[Dict[str, Any]]:
    """获取Top N可信发电量排名。

    这是所有排名查询的统一入口，替代原有的多个不一致实现。

    Args:
        conn: 数据库连接
        year: 年份（必需，防止混合不同年份）
        n: 排名数量
        country: 可选国家过滤
        confidence_threshold: 置信度阈值

    Returns:
        Top N 可信记录列表
    """
    return TrustworthyFilter.filter_records(
        conn,
        year=year,
        country=country,
        limit=n,
        offset=0,
        confidence_threshold=confidence_threshold
    )
