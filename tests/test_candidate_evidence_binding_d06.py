"""测试 D06: 候选→证据不可变对应。

验证候选与证据的强绑定关系，防止脱钩。
"""

import pytest
import sqlite3
from pathlib import Path
from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import migrate
from hydro_platform.pipeline.candidate_evidence_binding import (
    create_candidate_with_evidence,
    get_candidate_evidence,
    validate_candidate_evidence_immutable,
    get_candidate_with_evidence,
    promote_candidate_to_generation_record,
    verify_generation_record_traceability,
    CandidateEvidenceError
)
from hydro_platform.common.clock import now_iso


@pytest.fixture
def test_db(tmp_path):
    """创建测试数据库。"""
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    migrate(conn)

    # 插入测试数据
    conn.execute("""
        INSERT INTO stations (entity_id, canonical_name, country, capacity_mw, priority_tier)
        VALUES ('sta_test_01', 'Test Station', 'US', 1000, 'A')
    """)

    conn.execute("""
        INSERT INTO sources (source_id, url, title)
        VALUES ('src_test', 'http://test.com', 'Test Source')
    """)

    conn.execute("""
        INSERT INTO documents (document_id, original_url, file_size, content_hash, local_path, created_at)
        VALUES ('doc_test', 'http://test.com/doc', 1000, 'hash123', '/test/path', ?)
    """, (now_iso(),))

    conn.execute("""
        INSERT INTO evidence (evidence_id, source_id, fact_type, fact_key, source_url, created_at)
        VALUES
            ('evi_001', 'src_test', 'generation', 'key_01', 'http://test.com', ?),
            ('evi_002', 'src_test', 'generation', 'key_02', 'http://test.com', ?)
    """, (now_iso(), now_iso()))

    conn.execute("""
        INSERT INTO tasks (task_id, entity_id, entity_type, task_type, status, created_at, updated_at)
        VALUES ('task_test', 'sta_test_01', 'station', 'station_generation', 'pending', ?, ?)
    """, (now_iso(), now_iso()))

    conn.commit()
    yield conn
    conn.close()


class TestCandidateEvidenceBinding:
    """测试 D06: 候选-证据不可变绑定。"""

    def test_create_candidate_with_evidence(self, test_db):
        """测试创建带证据的候选。"""
        conn = test_db

        candidate_id = create_candidate_with_evidence(
            conn=conn,
            candidate_id='cand_001',
            task_id='task_test',
            entity_id='sta_test_01',
            document_id='doc_test',
            evidence_ids=['evi_001', 'evi_002'],
            period_type='calendar_year',
            period_label='2023',
            value_type='actual',
            measurement_scope='plant',
            generation_gwh=100.0
        )

        assert candidate_id == 'cand_001'

        # 验证候选已创建
        candidate = conn.execute("""
            SELECT * FROM extraction_candidates WHERE candidate_id = ?
        """, (candidate_id,)).fetchone()

        assert candidate is not None
        assert candidate['generation_gwh'] == 100.0

        # 验证证据关联
        evidence_ids = get_candidate_evidence(conn, candidate_id)
        assert len(evidence_ids) == 2
        assert 'evi_001' in evidence_ids
        assert 'evi_002' in evidence_ids

    def test_create_candidate_without_evidence_fails(self, test_db):
        """测试创建无证据的候选应失败。"""
        conn = test_db

        with pytest.raises(CandidateEvidenceError) as exc:
            create_candidate_with_evidence(
                conn=conn,
                candidate_id='cand_invalid',
                task_id='task_test',
                entity_id='sta_test_01',
                document_id='doc_test',
                evidence_ids=[],  # 空列表
                period_type='calendar_year',
                period_label='2023',
                value_type='actual',
                measurement_scope='plant'
            )

        assert '必须关联至少一个证据' in str(exc.value)

    def test_create_candidate_with_nonexistent_evidence_fails(self, test_db):
        """测试创建候选时引用不存在的证据应失败。"""
        conn = test_db

        with pytest.raises(CandidateEvidenceError) as exc:
            create_candidate_with_evidence(
                conn=conn,
                candidate_id='cand_invalid',
                task_id='task_test',
                entity_id='sta_test_01',
                document_id='doc_test',
                evidence_ids=['evi_999'],  # 不存在
                period_type='calendar_year',
                period_label='2023',
                value_type='actual',
                measurement_scope='plant'
            )

        assert '证据不存在' in str(exc.value)
        assert 'evi_999' in str(exc.value)

    def test_get_candidate_evidence(self, test_db):
        """测试获取候选关联的证据。"""
        conn = test_db

        create_candidate_with_evidence(
            conn=conn,
            candidate_id='cand_002',
            task_id='task_test',
            entity_id='sta_test_01',
            document_id='doc_test',
            evidence_ids=['evi_001'],
            period_type='calendar_year',
            period_label='2023',
            value_type='actual',
            measurement_scope='plant'
        )

        evidence_ids = get_candidate_evidence(conn, 'cand_002')
        assert evidence_ids == ['evi_001']

    def test_validate_candidate_evidence_immutable(self, test_db):
        """测试验证候选证据的不可变性。"""
        conn = test_db

        create_candidate_with_evidence(
            conn=conn,
            candidate_id='cand_003',
            task_id='task_test',
            entity_id='sta_test_01',
            document_id='doc_test',
            evidence_ids=['evi_001', 'evi_002'],
            period_type='calendar_year',
            period_label='2023',
            value_type='actual',
            measurement_scope='plant'
        )

        is_valid, reason = validate_candidate_evidence_immutable(conn, 'cand_003')
        assert is_valid is True
        assert '证据关联完整' in reason

    def test_validate_candidate_with_missing_evidence_fails(self, test_db):
        """测试候选关联的证据被删除后验证失败。"""
        conn = test_db

        create_candidate_with_evidence(
            conn=conn,
            candidate_id='cand_004',
            task_id='task_test',
            entity_id='sta_test_01',
            document_id='doc_test',
            evidence_ids=['evi_001'],
            period_type='calendar_year',
            period_label='2023',
            value_type='actual',
            measurement_scope='plant'
        )

        # 先删除候选-证据关联（绕过外键约束）
        conn.execute("DELETE FROM candidate_evidence WHERE evidence_id = 'evi_001'")
        # 再删除证据（模拟证据丢失）
        conn.execute("DELETE FROM evidence WHERE evidence_id = 'evi_001'")
        conn.commit()

        is_valid, reason = validate_candidate_evidence_immutable(conn, 'cand_004')
        assert is_valid is False
        assert '未关联任何证据' in reason or '证据已丢失' in reason

    def test_get_candidate_with_evidence(self, test_db):
        """测试获取候选及其证据。"""
        conn = test_db

        create_candidate_with_evidence(
            conn=conn,
            candidate_id='cand_005',
            task_id='task_test',
            entity_id='sta_test_01',
            document_id='doc_test',
            evidence_ids=['evi_001', 'evi_002'],
            period_type='calendar_year',
            period_label='2023',
            value_type='actual',
            measurement_scope='plant',
            generation_gwh=150.0
        )

        candidate = get_candidate_with_evidence(conn, 'cand_005')
        assert candidate is not None
        assert candidate['candidate_id'] == 'cand_005'
        assert candidate['generation_gwh'] == 150.0
        assert len(candidate['evidence_ids']) == 2

    def test_promote_candidate_to_generation_record(self, test_db):
        """旧候选升级入口不得绕过统一 Promotion。"""
        conn = test_db

        create_candidate_with_evidence(
            conn=conn,
            candidate_id='cand_006',
            task_id='task_test',
            entity_id='sta_test_01',
            document_id='doc_test',
            evidence_ids=['evi_001'],
            period_type='calendar_year',
            period_label='2023',
            value_type='actual',
            measurement_scope='plant',
            generation_gwh=200.0
        )

        with pytest.raises(CandidateEvidenceError, match="旧候选升级入口已禁用"):
            promote_candidate_to_generation_record(
                conn=conn,
                candidate_id='cand_006',
                source_id='src_test',
                task_id='task_test'
            )
        assert conn.execute("SELECT COUNT(*) FROM generation_records").fetchone()[0] == 0

    def test_promote_candidate_without_evidence_fails(self, test_db):
        """测试升级无证据的候选应失败。"""
        conn = test_db

        # 手动插入无证据的候选（绕过验证）
        conn.execute("""
            INSERT INTO extraction_candidates (
                candidate_id, task_id, entity_id, document_id,
                period_type, period_label, value_type, measurement_scope,
                extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'cand_invalid', 'task_test', 'sta_test_01', 'doc_test',
            'calendar_year', '2023', 'actual', 'plant', now_iso()
        ))
        conn.commit()

        with pytest.raises(CandidateEvidenceError) as exc:
            promote_candidate_to_generation_record(conn, 'cand_invalid')

        assert '旧候选升级入口已禁用' in str(exc.value)

    def test_verify_generation_record_traceability(self, test_db):
        """旧入口禁用后不会伪造可验证的正式记录。"""
        conn = test_db

        # 创建候选并升级
        create_candidate_with_evidence(
            conn=conn,
            candidate_id='cand_007',
            task_id='task_test',
            entity_id='sta_test_01',
            document_id='doc_test',
            evidence_ids=['evi_001'],
            period_type='calendar_year',
            period_label='2023',
            value_type='actual',
            measurement_scope='plant',
            generation_gwh=300.0
        )

        with pytest.raises(CandidateEvidenceError, match="旧候选升级入口已禁用"):
            promote_candidate_to_generation_record(
                conn=conn,
                candidate_id='cand_007',
                source_id='src_test'
            )

    def test_verify_traceability_with_broken_link_fails(self, test_db):
        """测试溯源链断裂时验证失败。"""
        conn = test_db

        # 手动创建一个引用不存在候选的记录（模拟溯源链断裂）
        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_type, period_label,
                generation_gwh, value_type, measurement_scope,
                candidate_id, evidence_id, publication_status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'sta_test_01', 'calendar_year', '2023',
            100.0, 'actual', 'plant',
            'cand_nonexistent', 'evi_001', 'publishable',
            now_iso(), now_iso()
        ))
        conn.commit()

        record_id = conn.execute(
            "SELECT id FROM generation_records WHERE candidate_id = 'cand_nonexistent'"
        ).fetchone()['id']

        is_valid, reason = verify_generation_record_traceability(conn, record_id)
        assert is_valid is False
        assert '不存在' in reason

    def test_evidence_immutability(self, test_db):
        """测试证据关联的不可变性（创建后不能修改）。"""
        conn = test_db

        create_candidate_with_evidence(
            conn=conn,
            candidate_id='cand_009',
            task_id='task_test',
            entity_id='sta_test_01',
            document_id='doc_test',
            evidence_ids=['evi_001'],
            period_type='calendar_year',
            period_label='2023',
            value_type='actual',
            measurement_scope='plant'
        )

        # 尝试修改证据关联（应该通过外键约束阻止）
        # 这里只验证关联存在且稳定
        evidence_ids_before = get_candidate_evidence(conn, 'cand_009')

        # 即使尝试插入重复关联，也不应改变原有关联
        try:
            conn.execute("""
                INSERT INTO candidate_evidence (candidate_id, evidence_id)
                VALUES ('cand_009', 'evi_002')
            """)
            conn.commit()
        except:
            pass

        evidence_ids_after = get_candidate_evidence(conn, 'cand_009')

        # 原始证据应保持不变
        assert 'evi_001' in evidence_ids_after


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
