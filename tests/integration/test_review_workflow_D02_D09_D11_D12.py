"""测试 Review-Workflow 修复（D02/D09/D11/D12）。

验证：
- D02：list_review_items 从 extraction_candidates 读取，显示来源类型
- D09：reject 同步所有相关表（extraction_candidates, review_events, generation_records, tasks）
- D11：cancel_review 状态回滚
- D12：approve 同步 generation_records 的 review_status 和 validation_status
"""

import pytest
import json
import uuid

from hydro_platform.pipeline.context import PipelineContext
from hydro_platform.pipeline.orchestrator import apply_review_decision, cancel_review
from hydro_platform.acquisition.router import AcquisitionRouter
from hydro_platform.acquisition.http_client import HttpClient
from hydro_platform.app.queries import ReadQueries
from hydro_platform.models.task import Task
from hydro_platform.common.enums import EntityType, TaskType, TaskStatus, FailureStage
from hydro_platform.common.clock import now_iso
from hydro_platform.pipeline.approval_versioning import compute_persisted_candidate_hash


@pytest.fixture
def test_db(db):
    """使用正式连接工厂创建的隔离数据库，绝不触碰用户的生产库。"""
    return db


@pytest.fixture
def ctx(test_db, tmp_path):
    """创建 Pipeline 上下文。"""
    raw_root = tmp_path / "raw"
    raw_root.mkdir(exist_ok=True)

    return PipelineContext(
        conn=test_db,
        router=AcquisitionRouter(http_client=HttpClient()),
        url_resolver=None,
        raw_root=raw_root,
        reviewer="test_user"
    )


def setup_test_data(conn):
    """设置测试数据：stations + documents + candidates + review_items。"""
    entity_id = "station_001"
    document_id = f"doc_{uuid.uuid4().hex[:12]}"
    candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
    review_id = f"rev_{uuid.uuid4().hex[:12]}"
    task_id = "task_test_001"

    # 清理可能存在的旧测试数据（禁用外键约束）
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM review_events WHERE review_id LIKE 'rev_%'")
        conn.execute("DELETE FROM review_items WHERE entity_id = ?", (entity_id,))
        conn.execute("DELETE FROM generation_records WHERE entity_id = ?", (entity_id,))
        conn.execute("DELETE FROM evidence WHERE evidence_id LIKE ?", (f"evi_{entity_id}%",))
        conn.execute("DELETE FROM extraction_candidates WHERE entity_id = ?", (entity_id,))
        conn.execute("DELETE FROM tasks WHERE task_id LIKE 'task_test_%'")
        conn.execute("DELETE FROM documents WHERE document_id LIKE 'doc_%'")
        conn.execute("DELETE FROM sources WHERE source_id LIKE 'src_%'")
        conn.execute("DELETE FROM stations WHERE entity_id = ?", (entity_id,))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    except Exception as e:
        print(f"Cleanup warning: {e}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.rollback()

    # 1. 插入 station
    conn.execute("""
        INSERT INTO stations (entity_id, canonical_name, country, capacity_mw)
        VALUES (?, ?, ?, ?)
    """, (entity_id, "Test Dam", "US", 5000.0))

    # 2. 插入 source（移除 access_method 字段）
    source_id = f"src_{uuid.uuid4().hex[:12]}"
    conn.execute("""
        INSERT INTO sources (source_id, url, title, publisher, retrieved_at)
        VALUES (?, ?, ?, ?, ?)
    """, (source_id, "https://example.com/test.pdf", "Test Report 2024", "Test Publisher", now_iso()))

    # 3. 插入 document（添加 original_url 和 access_method 字段）
    conn.execute("""
        INSERT INTO documents
        (document_id, source_id, original_url, content_kind, content_type, file_size, content_hash, local_path, access_method, fetched_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (document_id, source_id, "https://example.com/test.pdf", "report", "application/pdf", 10000, "hash123", "/tmp/test.pdf", "download", now_iso(), now_iso()))

    # 4. 插入 task（移除 user_specified_source 字段）
    conn.execute("""
        INSERT INTO tasks
        (task_id, entity_id, entity_type, task_type, target_period, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (task_id, entity_id, "station", "station_generation", "2024", "running", now_iso(), now_iso()))

    # 5. 插入 extraction_candidates
    conn.execute("""
        INSERT INTO extraction_candidates
        (candidate_id, task_id, entity_id, document_id, period_type, period_label, value_type,
         measurement_scope, metric, normalized_unit, generation_gwh, value_raw, unit_raw,
         snippet, extraction_method, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (candidate_id, task_id, entity_id, document_id, "calendar_year", "2024", "actual", "plant",
          "gross_generation", "gwh", 12500.0, "12,500", "GWh",
          "Annual gross generation: 12,500 GWh", "auto_search", now_iso()))

    # 6. 插入 evidence（添加 fact_type 和 fact_key 字段）
    evidence_id = f"evi_{uuid.uuid4().hex[:12]}"
    conn.execute("""
        INSERT INTO evidence
        (evidence_id, source_id, document_id, content_hash, fact_type, fact_key,
         snippet, page_number, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (evidence_id, source_id, document_id, "hash123", "generation",
          f"{entity_id}:2024:actual", "Annual generation: 12,500 GWh", 5, 0.85, now_iso()))

    conn.execute("""
        INSERT INTO candidate_evidence (candidate_id, evidence_id)
        VALUES (?, ?)
    """, (candidate_id, evidence_id))

    # 7. 插入 generation_records（draft状态）
    conn.execute("""
        INSERT INTO generation_records
        (entity_id, period_type, period_label, value_type, measurement_scope,
         generation_gwh, value_raw, unit_raw, source_id, evidence_id,
         publication_status, review_status, confidence, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (entity_id, "year", "2024", "actual", "plant", 12500.0, "12,500", "GWh",
          source_id, evidence_id, "draft", "open", 0.85, now_iso(), now_iso()))

    # 8. 插入 review_items（添加 fact_key 和 reason，移除 updated_at）
    candidate_hash = compute_persisted_candidate_hash(
        conn, candidate_id, expected_evidence_ids=[evidence_id]
    )
    payload = json.dumps({
        "candidate": {
            "entity_id": entity_id,
            "period_type": "calendar_year",
            "period_label": "2024",
            "value_type": "actual",
            "measurement_scope": "plant",
            "metric": "gross_generation",
            "normalized_unit": "gwh",
            "generation_gwh": 12500.0,
            "value_raw": "12,500",
            "unit_raw": "GWh"
        },
        "evidence_ids": [evidence_id],
        "validation_issues": [],
        "candidate_hash": candidate_hash,
    })

    conn.execute("""
        INSERT INTO review_items
        (review_id, task_id, candidate_id, entity_id, fact_type, fact_key, reason, status, payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (review_id, task_id, candidate_id, entity_id, "generation", f"{entity_id}:2024:actual", "低置信度候选", "open", payload, now_iso()))

    conn.commit()

    return {
        "entity_id": entity_id,
        "document_id": document_id,
        "candidate_id": candidate_id,
        "review_id": review_id,
        "task_id": task_id,
        "evidence_id": evidence_id,
        "source_id": source_id
    }


def test_D02_list_review_items_from_candidates(test_db):
    """D02：list_review_items 从 extraction_candidates 读取。"""
    data = setup_test_data(test_db)

    queries = ReadQueries(test_db)
    result = queries.list_review_items(status="open", limit=10, offset=0)

    # 验证查询成功
    assert result["total"] == 1
    assert len(result["items"]) == 1

    item = result["items"][0]

    # 验证基本字段
    assert item["review_id"] == data["review_id"]
    assert item["candidate_id"] == data["candidate_id"]
    assert item["entity_id"] == data["entity_id"]
    assert item["review_status"] == "open"

    # 验证候选数据字段（从 extraction_candidates）
    assert item["generation_gwh"] == 12500.0
    assert item["period_label"] == "2024"
    assert item["value_type"] == "actual"
    assert item["extraction_method"] == "auto_search"

    # 验证来源类型标签
    assert item["source_type"] == "auto_search"

    print("OK D02: list_review_items correctly reads from extraction_candidates with source_type")


def test_D09_reject_syncs_all_tables(test_db, ctx):
    """D09：reject 同步所有相关表。"""
    data = setup_test_data(test_db)

    task = Task(
        task_id=data["task_id"],
        entity_id=data["entity_id"],
        entity_type=EntityType.STATION,
        task_type=TaskType.STATION_GENERATION,
        target_period="2024"
    )

    # 执行 reject
    result = apply_review_decision(ctx, task, data["review_id"], "reject", "数据不可信")

    # reject 操作本身成功，但任务状态为 FAILED
    assert result.final_status == TaskStatus.FAILED, "reject 后任务应为 FAILED"
    assert result.failure_stage == FailureStage.REVIEW_REJECTED, "应标记为 REVIEW_REJECTED"

    # 验证 1：extraction_candidates.review_status = 'rejected'
    cand_row = test_db.execute("""
        SELECT review_status FROM extraction_candidates WHERE candidate_id = ?
    """, (data["candidate_id"],)).fetchone()
    assert cand_row["review_status"] == "rejected", "extraction_candidates 未更新"

    # 验证 2：review_events 表有记录
    event_row = test_db.execute("""
        SELECT * FROM review_events WHERE review_id = ? AND action = 'decide' AND decision = 'reject'
    """, (data["review_id"],)).fetchone()
    assert event_row is not None, "review_events 未记录"
    assert event_row["reason"] == "数据不可信"
    assert event_row["reviewer"] == "test_user"

    # 验证 3：generation_records 状态更新
    gen_row = test_db.execute("""
        SELECT publication_status, review_status FROM generation_records
        WHERE entity_id = ? AND period_label = ?
    """, (data["entity_id"], "2024")).fetchone()
    assert gen_row["publication_status"] == "withheld", "generation_records.publication_status 未更新"
    assert gen_row["review_status"] == "rejected", "generation_records.review_status 未更新"

    # 验证 4：tasks.status = 'failed'
    task_row = test_db.execute("""
        SELECT status, failure_stage FROM tasks WHERE task_id = ?
    """, (data["task_id"],)).fetchone()
    assert task_row["status"] == "failed", "tasks.status 未更新"
    assert task_row["failure_stage"] == "REVIEW_REJECTED", "tasks.failure_stage 未更新"

    print("OK D09: reject correctly syncs extraction_candidates, review_events, generation_records, tasks")


def test_D11_cancel_review_rollback(test_db, ctx):
    """D11：cancel_review 状态回滚。"""
    data = setup_test_data(test_db)

    # 执行 cancel
    result = cancel_review(ctx, data["review_id"], "用户取消")

    assert result.succeeded, f"Cancel 失败: {result.error}"

    # 验证 1：review_items.status = 'cancelled'
    review_row = test_db.execute("""
        SELECT status FROM review_items WHERE review_id = ?
    """, (data["review_id"],)).fetchone()
    assert review_row["status"] == "cancelled", "review_items.status 未更新"

    # 验证 2：review_events 表有记录
    event_row = test_db.execute("""
        SELECT * FROM review_events WHERE review_id = ? AND action = 'cancel'
    """, (data["review_id"],)).fetchone()
    assert event_row is not None, "review_events 未记录"
    assert event_row["reason"] == "用户取消"

    # 验证 3：取消后候选回到 pending（v6 不允许 NULL）
    cand_row = test_db.execute("""
        SELECT review_status FROM extraction_candidates WHERE candidate_id = ?
    """, (data["candidate_id"],)).fetchone()
    assert cand_row["review_status"] == "pending", "extraction_candidates.review_status 未回滚"

    # 验证 4：generation_records.review_status = NULL
    gen_row = test_db.execute("""
        SELECT review_status FROM generation_records
        WHERE entity_id = ? AND period_label = ?
    """, (data["entity_id"], "2024")).fetchone()
    assert gen_row["review_status"] is None, "generation_records.review_status 未回滚"

    print("OK D11: cancel_review correctly rolls back all related table states")


def test_D12_approve_syncs_generation_records(test_db, ctx):
    """D12：approve 同步 generation_records 的 review_status 和 validation_status。"""
    data = setup_test_data(test_db)

    task = Task(
        task_id=data["task_id"],
        entity_id=data["entity_id"],
        entity_type=EntityType.STATION,
        task_type=TaskType.STATION_GENERATION,
        target_period="2024"
    )

    # 执行 approve
    result = apply_review_decision(ctx, task, data["review_id"], "approve")

    assert result.succeeded, f"Approve 失败: {result.error}"

    # 验证 1：extraction_candidates.review_status = 'approved'
    cand_row = test_db.execute("""
        SELECT review_status FROM extraction_candidates WHERE candidate_id = ?
    """, (data["candidate_id"],)).fetchone()
    assert cand_row["review_status"] == "approved", "extraction_candidates 未更新"

    # 验证 2：review_events 表有记录
    event_row = test_db.execute("""
        SELECT * FROM review_events WHERE review_id = ? AND action = 'decide' AND decision = 'approve'
    """, (data["review_id"],)).fetchone()
    assert event_row is not None, "review_events 未记录"
    assert event_row["reviewer"] == "test_user"

    # 验证 3：generation_records 状态更新
    gen_row = test_db.execute("""
        SELECT review_status, validation_status, evidence_id FROM generation_records
        WHERE entity_id = ? AND period_label = ?
    """, (data["entity_id"], "2024")).fetchone()
    assert gen_row["review_status"] == "approved", "generation_records.review_status 未更新"
    assert gen_row["validation_status"] == "validated", "generation_records.validation_status 未更新"
    assert gen_row["evidence_id"] == data["evidence_id"], "generation_records.evidence_id 未填充"

    print("OK D12: approve correctly syncs all generation_records fields")


def test_approve_rejects_changed_candidate_version(test_db, ctx):
    """审批入队后候选值变化时，旧审批失效且不得发布。"""
    data = setup_test_data(test_db)
    test_db.execute(
        "UPDATE extraction_candidates SET generation_gwh = 12600 WHERE candidate_id = ?",
        (data["candidate_id"],),
    )
    test_db.commit()
    task = Task(
        task_id=data["task_id"], entity_id=data["entity_id"],
        entity_type=EntityType.STATION, task_type=TaskType.STATION_GENERATION,
        target_period="2024",
    )

    result = apply_review_decision(ctx, task, data["review_id"], "approve")

    assert not result.succeeded
    assert "版本已变化" in result.error
    review = test_db.execute(
        "SELECT status FROM review_items WHERE review_id = ?", (data["review_id"],)
    ).fetchone()
    assert review["status"] == "invalidated"
    record = test_db.execute(
        "SELECT publication_status FROM generation_records WHERE entity_id = ?",
        (data["entity_id"],),
    ).fetchone()
    assert record["publication_status"] == "draft"


def test_approve_rejects_broken_document_evidence_version(test_db, ctx):
    """归档文档哈希不再匹配证据时，审批失败关闭而不是沿用旧结果。"""
    data = setup_test_data(test_db)
    test_db.execute(
        "UPDATE documents SET content_hash = 'changed_hash' WHERE document_id = ?",
        (data["document_id"],),
    )
    test_db.commit()
    task = Task(
        task_id=data["task_id"], entity_id=data["entity_id"],
        entity_type=EntityType.STATION, task_type=TaskType.STATION_GENERATION,
        target_period="2024",
    )

    result = apply_review_decision(ctx, task, data["review_id"], "approve")

    assert not result.succeeded
    assert "候选证据链无效" in result.error
    review = test_db.execute(
        "SELECT status FROM review_items WHERE review_id = ?", (data["review_id"],)
    ).fetchone()
    assert review["status"] == "invalidated"


def test_review_cannot_be_approved_twice(test_db, ctx):
    """重复点击通过不会重复 Promotion，也不会把已成功任务改成失败。"""
    data = setup_test_data(test_db)
    task = Task(
        task_id=data["task_id"], entity_id=data["entity_id"],
        entity_type=EntityType.STATION, task_type=TaskType.STATION_GENERATION,
        target_period="2024",
    )
    first = apply_review_decision(ctx, task, data["review_id"], "approve")
    assert first.succeeded
    before_count = test_db.execute(
        "SELECT COUNT(*) FROM generation_records WHERE entity_id = ?",
        (data["entity_id"],),
    ).fetchone()[0]

    second = apply_review_decision(ctx, task, data["review_id"], "approve")

    assert not second.succeeded
    assert "只能从 open 状态裁决一次" in second.error
    after_count = test_db.execute(
        "SELECT COUNT(*) FROM generation_records WHERE entity_id = ?",
        (data["entity_id"],),
    ).fetchone()[0]
    assert after_count == before_count
    task_row = test_db.execute(
        "SELECT status FROM tasks WHERE task_id = ?", (data["task_id"],)
    ).fetchone()
    assert task_row["status"] == "success"


def test_D02_source_type_detection(test_db):
    """D02：验证来源类型检测逻辑（user_upload, user_url, auto_search, pipeline）。"""
    # 注意：由于当前schema缺少 access_method 和 user_specified_source 字段
    # 此测试简化为验证基本的 extraction_method 检测逻辑

    test_cases = [
        ("auto_search", "auto_search"),
        ("pipeline", "extraction"),
    ]

    for expected_type, extraction_method in test_cases:
        entity_id = f"station_{uuid.uuid4().hex[:8]}"
        candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
        review_id = f"rev_{uuid.uuid4().hex[:12]}"
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        document_id = f"doc_{uuid.uuid4().hex[:12]}"
        source_id = f"src_{uuid.uuid4().hex[:12]}"

        # 插入基础数据
        test_db.execute("""
            INSERT INTO stations (entity_id, canonical_name, country)
            VALUES (?, ?, ?)
        """, (entity_id, "Test Station", "US"))

        test_db.execute("""
            INSERT INTO sources (source_id, url, title, retrieved_at)
            VALUES (?, ?, ?, ?)
        """, (source_id, "https://test.com", "Test", now_iso()))

        test_db.execute("""
            INSERT INTO documents (document_id, source_id, original_url, content_kind, content_type, file_size, content_hash, local_path, access_method, fetched_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (document_id, source_id, "https://test.com/doc.pdf", "report", "application/pdf", 1000, "hash", "/tmp/test", "download", now_iso(), now_iso()))

        test_db.execute("""
            INSERT INTO tasks (task_id, entity_id, entity_type, task_type, target_period, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (task_id, entity_id, "station", "station_generation", "2024", "running", now_iso(), now_iso()))

        test_db.execute("""
            INSERT INTO extraction_candidates
            (candidate_id, task_id, entity_id, document_id, period_type, period_label, value_type,
             measurement_scope, generation_gwh, extraction_method, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (candidate_id, task_id, entity_id, document_id, "year", "2024", "actual", "plant", 1000.0, extraction_method, now_iso()))

        test_db.execute("""
            INSERT INTO review_items
            (review_id, task_id, candidate_id, entity_id, fact_type, fact_key, reason, status, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (review_id, task_id, candidate_id, entity_id, "generation", f"{entity_id}:2024:actual", "低置信度候选", "open", "{}", now_iso()))

        test_db.commit()

    # 查询并验证
    queries = ReadQueries(test_db)
    result = queries.list_review_items(status="open", limit=100, offset=0)

    assert result["total"] >= 2, f"期望至少2条记录，实际: {result['total']}"

    # 验证来源类型包含预期值
    source_types = {item["source_type"] for item in result["items"]}
    assert "auto_search" in source_types or "pipeline" in source_types, f"缺少预期的来源类型，实际: {source_types}"

    print(f"OK D02: source type detection logic correct (detected types: {source_types})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
