"""测试 Data-Trustworthiness 修复（D03-D08）。

验证：
- D03: request_more_evidence 不触发发布
- D04: 统一可信过滤器阻止不合格数据
- D08: 审批事务原子性
"""

import pytest
import sqlite3
from pathlib import Path
from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import migrate
from hydro_platform.pipeline.orchestrator import apply_review_decision
from hydro_platform.pipeline.context import PipelineContext
from hydro_platform.acquisition.router import AcquisitionRouter
from hydro_platform.acquisition.http_client import HttpClient
from hydro_platform.models.task import Task
from hydro_platform.common.enums import EntityType, TaskType, FailureStage
from hydro_platform.products.trustworthy_filter import (
    TrustworthyFilter,
    get_top_n_trustworthy
)
from hydro_platform.pipeline.approval_transaction import ApprovalTransaction
from hydro_platform.common.clock import now_iso


@pytest.fixture
def test_db(tmp_path):
    """创建测试数据库。"""
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    migrate(conn)

    # 插入测试电站
    conn.execute("""
        INSERT INTO stations (entity_id, canonical_name, country, capacity_mw, priority_tier)
        VALUES ('sta_test_01', 'Test Station', 'CN', 10000, 'A')
    """)

    # 插入测试来源（必须先于 evidence）
    conn.execute("""
        INSERT INTO sources (
            source_id, url, title, publisher
        ) VALUES (?, ?, ?, ?)
    """, (
        'src_test', 'http://test.com', 'Test Source', 'Test Publisher'
    ))

    # 插入测试证据（用于满足外键约束）
    conn.execute("""
        INSERT INTO evidence (
            evidence_id, source_id, fact_type, fact_key,
            source_url, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        'evi_001', 'src_test', 'generation', 'test_fact',
        'http://test.com', now_iso()
    ))

    conn.commit()

    yield conn
    conn.close()


class TestD03RequestMoreEvidence:
    """测试 D03: request_more_evidence 不应触发发布。"""

    def test_request_more_evidence_does_not_publish(self, test_db, tmp_path):
        """测试补充证据决策不发布数据。"""
        conn = test_db

        # 创建任务记录（必须先于 review_items）
        task_id = 'task_test_01'
        conn.execute("""
            INSERT INTO tasks (
                task_id, entity_id, entity_type, task_type,
                target_period, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id, 'sta_test_01', 'station', 'station_generation',
            '2023', 'pending', now_iso(), now_iso()
        ))

        # 创建复核项
        review_id = "rv_test_d03"
        conn.execute("""
            INSERT INTO review_items (
                review_id, entity_id, fact_type, fact_key, reason, status,
                payload, task_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            review_id, 'sta_test_01', 'generation', 'key_01',
            'LOW_CONFIDENCE', 'open',
            '{"candidate": {"period_label": "2023", "generation_gwh": 100, "value_type": "actual"}}',
            task_id, now_iso()
        ))
        conn.commit()

        # 创建任务对象
        task = Task(
            task_id=task_id,
            entity_id='sta_test_01',
            entity_type=EntityType.STATION,
            task_type=TaskType.STATION_GENERATION,
            target_period='2023'
        )

        # 创建上下文
        ctx = PipelineContext(
            conn=conn,
            router=AcquisitionRouter(http_client=HttpClient()),
            url_resolver=None,
            raw_root=tmp_path,
            reviewer="test_user"
        )

        # 执行 request_more_evidence 决策
        result = apply_review_decision(ctx, task, review_id, 'request_more_evidence')

        # 验证：任务应该保持 needs_review 状态
        assert result.final_status.value == 'needs_review'

        # 验证：不应创建 generation_records
        records = conn.execute(
            "SELECT * FROM generation_records WHERE entity_id = 'sta_test_01'"
        ).fetchall()
        assert len(records) == 0, "request_more_evidence 不应创建正式记录"

        # 验证：review_items 状态应该是 request_more_evidence
        review = conn.execute(
            "SELECT status FROM review_items WHERE review_id = ?", (review_id,)
        ).fetchone()
        assert review['status'] == 'request_more_evidence'


class TestD04TrustworthyFilter:
    """测试 D04: 统一可信过滤器。"""

    def test_filter_excludes_forecast(self, test_db):
        """测试过滤器排除预测值。"""
        conn = test_db

        # 插入预测值记录
        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_label, generation_gwh, value_type,
                period_type, measurement_scope, validation_status,
                publication_status, review_status, evidence_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'sta_test_01', '2023', 999.0, 'forecast',  # 预测值
            'calendar_year', 'plant', 'passed',
            'publishable', 'approved', 'evi_001'
        ))
        conn.commit()

        # 使用可信过滤器查询
        results = get_top_n_trustworthy(conn, year='2023', n=100)

        # 验证：预测值不应出现
        assert len(results) == 0, "预测值不应通过可信过滤器"

    def test_filter_excludes_quarter(self, test_db):
        """测试过滤器排除季度数据。"""
        conn = test_db

        # 插入季度数据
        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_label, generation_gwh, value_type,
                period_type, measurement_scope, validation_status,
                publication_status, review_status, evidence_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'sta_test_01', '2023', 999.0, 'actual',
            'quarter', 'plant', 'passed',  # 季度
            'publishable', 'approved', 'evi_001'
        ))
        conn.commit()

        results = get_top_n_trustworthy(conn, year='2023', n=100)
        assert len(results) == 0, "季度数据不应通过可信过滤器"

    def test_filter_excludes_region(self, test_db):
        """测试过滤器排除区域合计。"""
        conn = test_db

        # 插入区域合计数据
        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_label, generation_gwh, value_type,
                period_type, measurement_scope, validation_status,
                publication_status, review_status, evidence_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'sta_test_01', '2023', 999.0, 'actual',
            'calendar_year', 'region', 'passed',  # 区域合计
            'publishable', 'approved', 'evi_001'
        ))
        conn.commit()

        results = get_top_n_trustworthy(conn, year='2023', n=100)
        assert len(results) == 0, "区域合计不应通过可信过滤器"

    def test_filter_excludes_failed_validation(self, test_db):
        """测试过滤器排除校验失败的数据。"""
        conn = test_db

        # 插入校验失败的数据
        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_label, generation_gwh, value_type,
                period_type, measurement_scope, validation_status,
                publication_status, review_status, evidence_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'sta_test_01', '2023', 999.0, 'actual',
            'calendar_year', 'plant', 'failed',  # 校验失败
            'publishable', 'approved', 'evi_001'
        ))
        conn.commit()

        results = get_top_n_trustworthy(conn, year='2023', n=100)
        assert len(results) == 0, "校验失败的数据不应通过过滤器"

    def test_filter_excludes_no_evidence(self, test_db):
        """测试过滤器排除无证据的数据。"""
        conn = test_db

        # 插入无证据的数据
        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_label, generation_gwh, value_type,
                period_type, measurement_scope, validation_status,
                publication_status, review_status, evidence_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'sta_test_01', '2023', 999.0, 'actual',
            'calendar_year', 'plant', 'passed',
            'publishable', 'approved', None  # 无证据
        ))
        conn.commit()

        results = get_top_n_trustworthy(conn, year='2023', n=100)
        assert len(results) == 0, "无证据的数据不应通过过滤器"

    def test_filter_accepts_valid_record(self, test_db):
        """测试过滤器接受合格数据。"""
        conn = test_db

        # 插入完全合格的数据
        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_label, generation_gwh, value_type,
                period_type, measurement_scope, validation_status,
                publication_status, review_status, evidence_id, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'sta_test_01', '2023', 100.0, 'actual',
            'calendar_year', 'plant', 'passed',
            'publishable', 'approved', 'evi_001', 0.9
        ))
        conn.commit()

        results = get_top_n_trustworthy(conn, year='2023', n=100)
        assert len(results) == 1, "合格数据应通过过滤器"
        assert results[0]['generation_gwh'] == 100.0


class TestD08ApprovalTransaction:
    """测试 D08: 审批事务原子性。"""

    def test_transaction_rollback_on_error(self, test_db, tmp_path):
        """测试事务失败时正确回滚。"""
        conn = test_db

        # 创建审批事务
        transaction = ApprovalTransaction(conn)

        review_id = "rv_test_d08"
        task_id = "task_test_d08"

        # 创建任务（必须先于 review_items）
        conn.execute("""
            INSERT INTO tasks (
                task_id, entity_id, entity_type, task_type,
                target_period, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id, 'sta_test_01', 'station', 'station_generation',
            '2023', 'pending', now_iso(), now_iso()
        ))

        # 创建复核项
        conn.execute("""
            INSERT INTO review_items (
                review_id, entity_id, fact_type, fact_key,
                reason, status, payload, task_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            review_id, 'sta_test_01', 'generation', 'key_d08',
            'TEST', 'open', '{}', task_id, now_iso()
        ))
        conn.commit()

        # 尝试事务，但故意触发错误
        try:
            with transaction.atomic_approval(review_id, task_id) as tx:
                tx.mark_review_approved("test_user")
                # 故意插入无效数据触发错误
                tx.promote_to_generation_records(
                    entity_id='INVALID_ID',  # 不存在的实体
                    period_label='2023',
                    generation_gwh=100.0,
                    evidence_id='evi_test'
                )
                # 这里应该因为外键约束失败
        except Exception:
            pass  # 预期会失败

        # 验证：review_items 应该回滚，仍是 open 状态
        review = conn.execute(
            "SELECT status FROM review_items WHERE review_id = ?", (review_id,)
        ).fetchone()
        assert review['status'] == 'open', "事务失败应回滚 review_items"

        # 验证：不应有 generation_records
        records = conn.execute(
            "SELECT * FROM generation_records WHERE entity_id = 'INVALID_ID'"
        ).fetchall()
        assert len(records) == 0, "事务失败不应留下部分数据"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
