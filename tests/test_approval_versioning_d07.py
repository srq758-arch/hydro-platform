"""测试 D07: 防止旧审批复用。

验证候选内容变化后，旧审批不会被错误复用。
"""

import pytest
import sqlite3
import json
from pathlib import Path
from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import migrate
from hydro_platform.pipeline.approval_versioning import (
    compute_candidate_hash,
    add_candidate_hash_to_review,
    check_approval_reuse,
    invalidate_stale_approvals,
    create_review_with_hash,
    should_create_new_review
)
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
        VALUES ('sta_test_01', 'Test Station', 'US', 1000, 'A')
    """)

    conn.commit()
    yield conn
    conn.close()


class TestApprovalVersioning:
    """测试 D07: 审批版本化和防复用。"""

    def test_compute_candidate_hash_stable(self):
        """测试候选哈希计算的稳定性。"""
        candidate1 = {
            'entity_id': 'sta_001',
            'period_label': '2023',
            'generation_gwh': 100.0,
            'value_type': 'actual',
            'source_id': 'src_001',
            'evidence_id': 'evi_001'
        }

        candidate2 = {
            'entity_id': 'sta_001',
            'period_label': '2023',
            'generation_gwh': 100.0,
            'value_type': 'actual',
            'source_id': 'src_001',
            'evidence_id': 'evi_001'
        }

        hash1 = compute_candidate_hash(candidate1)
        hash2 = compute_candidate_hash(candidate2)

        assert hash1 == hash2, "相同数据应产生相同哈希"
        assert len(hash1) == 64, "SHA256 哈希应为64字符"

    def test_compute_candidate_hash_different(self):
        """测试不同候选产生不同哈希。"""
        candidate1 = {
            'entity_id': 'sta_001',
            'period_label': '2023',
            'generation_gwh': 100.0
        }

        candidate2 = {
            'entity_id': 'sta_001',
            'period_label': '2023',
            'generation_gwh': 101.0  # 数值变化
        }

        hash1 = compute_candidate_hash(candidate1)
        hash2 = compute_candidate_hash(candidate2)

        assert hash1 != hash2, "不同数据应产生不同哈希"

    def test_create_review_with_hash(self, test_db):
        """测试创建带哈希的复核项。"""
        conn = test_db

        candidate_data = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 100.0,
            'value_type': 'actual'
        }

        candidate_hash = create_review_with_hash(
            conn=conn,
            review_id='rv_test_01',
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            reason='TEST',
            candidate_data=candidate_data
        )

        # 验证哈希已创建
        assert candidate_hash is not None
        assert len(candidate_hash) == 64

        # 验证复核项已插入
        review = conn.execute("""
            SELECT payload FROM review_items WHERE review_id = 'rv_test_01'
        """).fetchone()

        assert review is not None
        payload = json.loads(review['payload'])
        assert payload['candidate_hash'] == candidate_hash

    def test_check_approval_reuse_same_hash(self, test_db):
        """测试相同哈希可以复用审批。"""
        conn = test_db

        candidate_data = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 100.0
        }

        # 创建并批准旧复核项
        old_hash = create_review_with_hash(
            conn=conn,
            review_id='rv_old',
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            reason='TEST',
            candidate_data=candidate_data
        )

        conn.execute("""
            UPDATE review_items
            SET status = 'approved', resolved_at = ?
            WHERE review_id = 'rv_old'
        """, (now_iso(),))
        conn.commit()

        # 检查新候选（相同数据）是否可复用
        can_reuse, old_review_id = check_approval_reuse(
            conn=conn,
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            new_candidate_hash=old_hash
        )

        assert can_reuse is True, "相同哈希应可复用"
        assert old_review_id == 'rv_old'

    def test_check_approval_reuse_different_hash(self, test_db):
        """测试不同哈希不能复用审批。"""
        conn = test_db

        old_candidate = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 100.0
        }

        # 创建并批准旧复核项
        create_review_with_hash(
            conn=conn,
            review_id='rv_old',
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            reason='TEST',
            candidate_data=old_candidate
        )

        conn.execute("""
            UPDATE review_items
            SET status = 'approved', resolved_at = ?
            WHERE review_id = 'rv_old'
        """, (now_iso(),))
        conn.commit()

        # 新候选数据变化
        new_candidate = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 101.0  # 数值变化
        }
        new_hash = compute_candidate_hash(new_candidate)

        # 检查是否可复用
        can_reuse, old_review_id = check_approval_reuse(
            conn=conn,
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            new_candidate_hash=new_hash
        )

        assert can_reuse is False, "不同哈希不应复用"
        assert old_review_id == 'rv_old'

    def test_invalidate_stale_approvals(self, test_db):
        """测试使过期审批失效。"""
        conn = test_db

        old_candidate = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 100.0
        }

        # 创建并批准旧复核项
        create_review_with_hash(
            conn=conn,
            review_id='rv_old',
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            reason='TEST',
            candidate_data=old_candidate
        )

        conn.execute("""
            UPDATE review_items
            SET status = 'approved', resolved_at = ?
            WHERE review_id = 'rv_old'
        """, (now_iso(),))
        conn.commit()

        # 新候选数据变化
        new_candidate = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 101.0
        }
        new_hash = compute_candidate_hash(new_candidate)

        # 使旧审批失效
        count = invalidate_stale_approvals(
            conn=conn,
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            new_candidate_hash=new_hash
        )

        assert count == 1, "应失效1个旧审批"

        # 验证状态已更新
        review = conn.execute("""
            SELECT status FROM review_items WHERE review_id = 'rv_old'
        """).fetchone()

        assert review['status'] == 'invalidated', "旧审批应标记为失效"

    def test_should_create_new_review_no_old(self, test_db):
        """测试无旧审批时应创建新复核。"""
        conn = test_db

        candidate = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 100.0
        }

        should_create, reason = should_create_new_review(
            conn=conn,
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            new_candidate_data=candidate
        )

        assert should_create is True, "无旧审批应创建新复核"
        assert '无旧审批' in reason

    def test_should_create_new_review_content_changed(self, test_db):
        """测试候选内容变化时应创建新复核。"""
        conn = test_db

        old_candidate = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 100.0
        }

        # 创建并批准旧复核项
        create_review_with_hash(
            conn=conn,
            review_id='rv_old',
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            reason='TEST',
            candidate_data=old_candidate
        )

        conn.execute("""
            UPDATE review_items
            SET status = 'approved', resolved_at = ?
            WHERE review_id = 'rv_old'
        """, (now_iso(),))
        conn.commit()

        # 新候选内容变化
        new_candidate = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 105.0  # 数值变化
        }

        should_create, reason = should_create_new_review(
            conn=conn,
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            new_candidate_data=new_candidate
        )

        assert should_create is True, "内容变化应创建新复核"
        assert '已变化' in reason

    def test_should_not_create_review_content_same(self, test_db):
        """测试候选内容未变化时不应创建新复核。"""
        conn = test_db

        candidate = {
            'entity_id': 'sta_test_01',
            'period_label': '2023',
            'generation_gwh': 100.0
        }

        # 创建并批准旧复核项
        create_review_with_hash(
            conn=conn,
            review_id='rv_old',
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            reason='TEST',
            candidate_data=candidate
        )

        conn.execute("""
            UPDATE review_items
            SET status = 'approved', resolved_at = ?
            WHERE review_id = 'rv_old'
        """, (now_iso(),))
        conn.commit()

        # 新候选内容完全相同
        should_create, reason = should_create_new_review(
            conn=conn,
            entity_id='sta_test_01',
            fact_type='generation',
            fact_key='key_01',
            new_candidate_data=candidate
        )

        assert should_create is False, "内容未变化不应创建新复核"
        assert '可复用' in reason

    def test_hash_ignores_irrelevant_fields(self):
        """测试哈希忽略不相关字段（如创建时间）。"""
        candidate1 = {
            'entity_id': 'sta_001',
            'generation_gwh': 100.0,
            'created_at': '2023-01-01',  # 不应影响哈希
            'updated_at': '2023-01-02'   # 不应影响哈希
        }

        candidate2 = {
            'entity_id': 'sta_001',
            'generation_gwh': 100.0,
            'created_at': '2024-01-01',  # 不同时间
            'updated_at': '2024-01-02'   # 不同时间
        }

        hash1 = compute_candidate_hash(candidate1)
        hash2 = compute_candidate_hash(candidate2)

        # 时间字段不在 key_fields 中，不影响哈希
        assert hash1 == hash2, "创建时间不应影响哈希"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
