"""测试 D05: 实体归属验证。

验证防止 entity_id 误判（如 US70 被识别为 CN 电站）。
"""

import pytest
import sqlite3
from pathlib import Path
from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import migrate
from hydro_platform.pipeline.entity_attribution import (
    validate_entity_attribution,
    validate_candidate_attribution,
    check_and_log_attribution,
    EntityAttributionError
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
        VALUES
            ('sta_us_01', 'Grand Coulee Dam', 'US', 6809, 'A'),
            ('sta_cn_01', 'Three Gorges Dam', 'CN', 22500, 'A'),
            ('sta_br_01', 'Itaipu Dam', 'BR', 14000, 'A')
    """)

    # 插入测试来源
    conn.execute("""
        INSERT INTO sources (source_id, url, title, publisher)
        VALUES
            ('src_eia', 'https://www.eia.gov/electricity/data.php', 'EIA Electric Power Monthly', 'U.S. EIA'),
            ('src_cn', 'http://www.stats.gov.cn/energy/', 'China Energy Statistics', 'NBS China'),
            ('src_br', 'http://www.aneel.gov.br/dados', 'ANEEL Data', 'ANEEL Brazil')
    """)

    # 插入测试证据
    conn.execute("""
        INSERT INTO evidence (
            evidence_id, source_id, fact_type, fact_key,
            source_url, snippet, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        'evi_us_01', 'src_eia', 'generation', 'test_us',
        'https://www.eia.gov/electricity/data.php',
        'Grand Coulee Dam generated 21,000 GWh in the United States',
        now_iso()
    ))

    conn.execute("""
        INSERT INTO evidence (
            evidence_id, source_id, fact_type, fact_key,
            source_url, snippet, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        'evi_cn_01', 'src_cn', 'generation', 'test_cn',
        'http://www.stats.gov.cn/energy/',
        '三峡大坝在中国发电量达到 98,000 GWh',
        now_iso()
    ))

    conn.commit()

    yield conn
    conn.close()


class TestEntityAttribution:
    """测试 D05: 实体归属验证。"""

    def test_valid_us_attribution(self, test_db):
        """测试美国电站+美国数据源的正确归属。"""
        conn = test_db

        is_valid, reason = validate_entity_attribution(
            conn=conn,
            entity_id='sta_us_01',
            source_country='US',
            source_text='EIA United States power generation data',
            evidence_snippet='Grand Coulee Dam in the U.S.'
        )

        assert is_valid, f"美国电站+美国数据应通过验证: {reason}"

    def test_valid_cn_attribution(self, test_db):
        """测试中国电站+中国数据源的正确归属。"""
        conn = test_db

        is_valid, reason = validate_entity_attribution(
            conn=conn,
            entity_id='sta_cn_01',
            source_country='CN',
            source_text='中国能源统计年鉴',
            evidence_snippet='三峡大坝位于中国'
        )

        assert is_valid, f"中国电站+中国数据应通过验证: {reason}"

    def test_invalid_us_station_cn_source(self, test_db):
        """测试美国电站但数据源明确指向中国（应拒绝）。"""
        conn = test_db

        is_valid, reason = validate_entity_attribution(
            conn=conn,
            entity_id='sta_us_01',  # 美国电站
            source_country='CN',     # 但来自中国数据源
            source_text='中国电力统计',
            evidence_snippet='位于中国的水电站'
        )

        assert not is_valid, "美国电站+中国数据源应被拒绝"
        assert '国家不匹配' in reason or 'US' in reason

    def test_invalid_cn_station_us_source(self, test_db):
        """测试中国电站但数据源明确指向美国（应拒绝）。"""
        conn = test_db

        is_valid, reason = validate_entity_attribution(
            conn=conn,
            entity_id='sta_cn_01',  # 中国电站
            source_country='US',     # 但来自美国数据源
            source_text='EIA U.S. electric power data',
            evidence_snippet='hydroelectric plants in the United States'
        )

        assert not is_valid, "中国电站+美国数据源应被拒绝"
        assert '国家不匹配' in reason or 'CN' in reason

    def test_text_marker_mismatch(self, test_db):
        """测试文本标识与实体国家不匹配。"""
        conn = test_db

        # 美国电站，但文本明确指向中国
        is_valid, reason = validate_entity_attribution(
            conn=conn,
            entity_id='sta_us_01',
            evidence_snippet='这是中国的三峡大坝发电数据'
        )

        assert not is_valid, "文本指向中国但实体是美国应被拒绝"
        assert '中国' in reason or 'CN' in reason

    def test_candidate_attribution_with_eia_source(self, test_db):
        """测试基于数据库记录的候选归属验证（EIA源）。"""
        conn = test_db

        # 美国电站 + EIA数据源 = 正确
        is_valid, reason = validate_candidate_attribution(
            conn=conn,
            entity_id='sta_us_01',
            source_id='src_eia',
            evidence_id='evi_us_01'
        )

        assert is_valid, f"美国电站+EIA数据源应通过: {reason}"

    def test_candidate_attribution_mismatch(self, test_db):
        """测试候选归属不匹配（中国电站+EIA源）。"""
        conn = test_db

        # 中国电站 + EIA数据源 = 错误
        is_valid, reason = validate_candidate_attribution(
            conn=conn,
            entity_id='sta_cn_01',  # 中国电站
            source_id='src_eia',     # 美国EIA数据源
            evidence_id='evi_us_01'  # 美国证据
        )

        assert not is_valid, "中国电站+EIA数据源应被拒绝"

    def test_check_and_log_with_raise(self, test_db):
        """测试检查函数在失败时抛出异常。"""
        conn = test_db

        # 应该抛出异常
        with pytest.raises(EntityAttributionError):
            check_and_log_attribution(
                conn=conn,
                entity_id='sta_cn_01',  # 中国电站
                source_id='src_eia',     # 美国数据源
                raise_on_failure=True
            )

    def test_check_and_log_without_raise(self, test_db):
        """测试检查函数在失败时不抛出异常。"""
        conn = test_db

        # 应该返回 False，但不抛异常
        result = check_and_log_attribution(
            conn=conn,
            entity_id='sta_cn_01',  # 中国电站
            source_id='src_eia',     # 美国数据源
            raise_on_failure=False
        )

        assert result is False, "验证失败应返回 False"

    def test_nonexistent_entity(self, test_db):
        """测试不存在的实体。"""
        conn = test_db

        is_valid, reason = validate_entity_attribution(
            conn=conn,
            entity_id='sta_invalid_999',
            source_country='US'
        )

        assert not is_valid, "不存在的实体应被拒绝"
        assert '不存在' in reason

    def test_international_source_flexibility(self, test_db):
        """测试国际数据源的灵活性（世界银行等）。"""
        conn = test_db

        # 插入国际数据源
        conn.execute("""
            INSERT INTO sources (source_id, url, title, publisher)
            VALUES ('src_wb', 'https://data.worldbank.org/', 'World Bank Data', 'World Bank')
        """)
        conn.commit()

        # 世界银行数据源可以匹配任何国家
        is_valid_us, _ = validate_candidate_attribution(
            conn=conn,
            entity_id='sta_us_01',
            source_id='src_wb'
        )

        is_valid_cn, _ = validate_candidate_attribution(
            conn=conn,
            entity_id='sta_cn_01',
            source_id='src_wb'
        )

        # 国际源因为没有明确国家标识，不会触发国家不匹配
        # （在当前实现中，source_country 会是 None，不触发规则1）
        assert is_valid_us or is_valid_cn, "国际数据源应该有一定灵活性"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
