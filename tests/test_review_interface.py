"""测试任务 2.1：GUI 复核界面开发 - 验证问题显示功能

验证：
1. 后端 API 返回 validation_issues
2. 前端能正确显示验证问题
3. 不同严重度的问题有不同样式
"""

import json
import sqlite3
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.app.queries import ReadQueries
from hydro_platform.database.connection import connect
from hydro_platform.common.clock import now_iso


def setup_test_data(conn: sqlite3.Connection):
    """创建测试数据：带验证问题的复核记录"""

    # 1. 创建测试电站
    conn.execute("""
        INSERT OR IGNORE INTO stations (entity_id, entity_type, canonical_name, country, capacity_mw)
        VALUES ('test_station_rv', 'station', 'Test Review Station', 'CN', 5000.0)
    """)

    # 2. 创建测试来源
    conn.execute("""
        INSERT OR IGNORE INTO sources (source_id, url, title, publisher)
        VALUES ('src_test_rv', 'http://test.com/data', 'Test Source', 'Test Publisher')
    """)

    # 3. 创建测试证据
    conn.execute("""
        INSERT OR IGNORE INTO evidence (
            evidence_id, source_id, fact_type, fact_key,
            snippet, page_number, table_reference, confidence, created_at
        )
        VALUES (
            'ev_test_rv', 'src_test_rv', 'generation', 'test_key',
            'Generation in 2023: 15000 GWh', 1, 'Table 1', 0.85, ?
        )
    """, (now_iso(),))

    # 4. 创建待复核的发电量记录
    conn.execute("""
        INSERT OR REPLACE INTO generation_records (
            entity_id, period_type, period_label, generation_gwh,
            value_type, measurement_scope, unit_raw, value_raw,
            source_id, evidence_id, confidence, validation_status,
            review_status, publication_status, created_at, updated_at
        )
        VALUES (
            'test_station_rv', 'year', '2023', 15000.0,
            'actual', 'plant', 'GWh', '15000',
            'src_test_rv', 'ev_test_rv', 0.85, 'passed_with_issues',
            'open', 'draft', ?, ?
        )
    """, (now_iso(), now_iso()))

    record_id = conn.execute(
        "SELECT id FROM generation_records WHERE entity_id = 'test_station_rv'"
    ).fetchone()['id']

    # 5. 创建复核项，包含多种严重度的验证问题
    validation_issues = [
        {
            "code": "YEAR_MISMATCH",
            "message": "抽取年份2023与目标年份2022不一致，请确认数据正确性",
            "severity": "MEDIUM"
        },
        {
            "code": "LOW_CONFIDENCE",
            "message": "抽取置信度较低(0.85)，建议人工核验",
            "severity": "LOW"
        },
        {
            "code": "UNIT_UNCLEAR",
            "message": "单位识别存在歧义，已标准化为GWh但需确认",
            "severity": "MEDIUM"
        }
    ]

    payload = json.dumps({
        "candidate": {
            "entity_id": "test_station_rv",
            "period_type": "year",
            "period_label": "2023",
            "generation_gwh": 15000.0,
            "value_type": "actual",
            "measurement_scope": "plant",
            "unit_raw": "GWh",
            "value_raw": "15000",
            "confidence": 0.85
        },
        "validation_issues": validation_issues,
        "evidence_ids": ["ev_test_rv"],
        "is_top100": False
    }, ensure_ascii=False)

    conn.execute("""
        INSERT OR REPLACE INTO review_items (
            review_id, entity_id, fact_type, fact_key,
            reason, status, payload, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        'rv_test_001',
        'test_station_rv',
        'generation',
        'year::2023::actual::plant',
        'YEAR_MISMATCH; LOW_CONFIDENCE; UNIT_UNCLEAR',
        'open',
        payload,
        now_iso()
    ))

    conn.commit()
    return record_id


def test_backend_validation_issues(test_db):
    """测试后端API返回validation_issues"""
    print("\n=== 测试 1: 后端API返回验证问题 ===")

    conn = test_db
    record_id = setup_test_data(conn)
    print(f"[OK] 创建测试数据，record_id={record_id}")

    # 测试 get_review_detail
    queries = ReadQueries(conn)
    detail = queries.get_review_detail(record_id)

    assert detail is not None, "应返回记录详情"
    print(f"[OK] 获取到记录详情: {detail['canonical_name']}")

    assert 'validation_issues' in detail, "应包含validation_issues字段"
    print(f"[OK] 包含validation_issues字段")

    issues = detail['validation_issues']
    assert isinstance(issues, list), "validation_issues应为列表"
    assert len(issues) == 3, f"应有3个验证问题，实际{len(issues)}个"
    print(f"[OK] 返回{len(issues)}个验证问题")

    # 检查问题结构
    for i, issue in enumerate(issues, 1):
        assert 'code' in issue, f"问题{i}应有code字段"
        assert 'message' in issue, f"问题{i}应有message字段"
        assert 'severity' in issue, f"问题{i}应有severity字段"
        severity = issue['severity']
        assert severity in ['HIGH', 'MEDIUM', 'LOW'], f"问题{i}严重度无效: {severity}"
        print(f"  问题{i}: [{severity}] {issue['code']} - {issue['message'][:40]}...")

    print("\n[OK] 后端API测试通过")
    return True

def test_validation_issues_structure(test_db):
    """测试不同严重度的验证问题"""
    print("\n=== 测试 2: 验证问题严重度分类 ===")

    conn = test_db
    record_id = setup_test_data(conn)
    queries = ReadQueries(conn)
    detail = queries.get_review_detail(record_id)

    issues = detail['validation_issues']
    severity_counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}

    for issue in issues:
        severity = issue['severity']
        severity_counts[severity] += 1

    print(f"严重度统计:")
    print(f"  HIGH (严重):   {severity_counts['HIGH']} 个")
    print(f"  MEDIUM (警告): {severity_counts['MEDIUM']} 个")
    print(f"  LOW (提示):    {severity_counts['LOW']} 个")

    assert severity_counts['MEDIUM'] == 2, "应有2个MEDIUM问题"
    assert severity_counts['LOW'] == 1, "应有1个LOW问题"
    assert severity_counts['HIGH'] == 0, "应有0个HIGH问题"

    print("\n[OK] 严重度分类正确")
    return True

def test_no_validation_issues(test_db):
    """测试没有验证问题的记录"""
    print("\n=== 测试 3: 无验证问题的记录 ===")

    conn = test_db
    # 创建没有验证问题的记录
    conn.execute("""
        INSERT OR IGNORE INTO stations (entity_id, entity_type, canonical_name, country, capacity_mw)
        VALUES ('test_station_clean', 'station', 'Clean Station', 'CN', 3000.0)
    """)

    conn.execute("""
        INSERT OR REPLACE INTO generation_records (
            entity_id, period_type, period_label, generation_gwh,
            value_type, measurement_scope, unit_raw, value_raw,
            validation_status, review_status, publication_status,
            created_at, updated_at
        )
        VALUES (
            'test_station_clean', 'year', '2022', 8000.0,
            'actual', 'plant', 'GWh', '8000',
            'passed', 'not_required', 'draft', ?, ?
        )
    """, (now_iso(), now_iso()))

    conn.commit()

    record_id = conn.execute(
        "SELECT id FROM generation_records WHERE entity_id = 'test_station_clean'"
    ).fetchone()['id']

    queries = ReadQueries(conn)
    detail = queries.get_review_detail(record_id)

    assert detail is not None, "应返回记录详情"
    assert 'validation_issues' in detail, "应包含validation_issues字段"
    assert detail['validation_issues'] == [], "validation_issues应为空列表"

    print("[OK] 无验证问题时返回空列表")
    return True

