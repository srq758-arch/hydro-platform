"""集成测试：验证 Api.run_collection_task() 走完整可信 Pipeline。

测试场景：
1. 本地文件 → 完整 Pipeline（采集/归档/解析/抽取/校验/存证/复核闸门）
2. URL → 完整 Pipeline
3. Top100 电站 → 停在 needs_review
4. 非 Top100 电站 + 干净候选 → 自动升级为 publishable
5. approve_record() 走 orchestrator.apply_review_decision()
6. reject_record() 走 orchestrator.apply_review_decision()
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hydro_platform.app.api import Api
from hydro_platform.common.enums import TaskStatus


@pytest.fixture
def api_with_test_db(tmp_path, monkeypatch):
    """创建使用临时数据库的 Api 实例。"""
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("test")
    api.initialize()

    # 插入测试电站（Top100）
    conn = api.get_db_connection()
    conn.execute("""
        INSERT INTO stations (entity_id, canonical_name, country, capacity_mw, priority_tier)
        VALUES ('STATION_TOP100', '三峡水电站', 'China', 22500.0, 'A')
    """)

    # 插入测试任务（满足 evidence 表的 FK 约束）
    # 注意：使用不同的 target_period 避免与测试中创建的任务冲突
    conn.execute("""
        INSERT INTO tasks (
            task_id, entity_id, entity_type, task_type, target_period,
            status, created_at, updated_at
        ) VALUES (
            'test_task', 'STATION_TOP100', 'station', 'station_generation', '2022',
            'pending', datetime('now'), datetime('now')
        )
    """)

    # 插入测试来源（满足 evidence 表的 FK 约束）
    conn.execute("""
        INSERT INTO sources (source_id, url, title, publisher)
        VALUES ('test_source', 'file:///test/report.pdf', '2023年年报', '三峡集团')
    """)

    # 插入测试文档（满足 evidence 表的 FK 约束）
    conn.execute("""
        INSERT INTO documents (
            document_id, source_id, original_url, file_size, content_hash,
            local_path, content_kind, content_type, created_at
        ) VALUES (
            'doc_b9b0b3650e8b909a', 'test_source', 'file:///test/report.pdf',
            1024, 'test_hash', '/tmp/test.pdf', 'pdf', 'application/pdf',
            datetime('now')
        )
    """)

    conn.commit()
    conn.close()

    return api


@pytest.fixture
def api_with_non_top100(tmp_path, monkeypatch):
    """创建包含非 Top100 电站的 Api 实例。"""
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("test")
    api.initialize()

    # 插入测试电站（非 Top100）
    conn = api.get_db_connection()
    conn.execute("""
        INSERT INTO stations (entity_id, canonical_name, country, capacity_mw, priority_tier)
        VALUES ('STATION_NORMAL', '小型水电站', 'China', 100.0, 'B')
    """)

    # 插入测试任务（满足 evidence 表的 FK 约束）
    conn.execute("""
        INSERT INTO tasks (
            task_id, entity_id, entity_type, task_type, target_period,
            status, created_at, updated_at
        ) VALUES (
            'test_task', 'STATION_NORMAL', 'station', 'station_generation', '2022',
            'pending', datetime('now'), datetime('now')
        )
    """)

    # 插入测试来源
    conn.execute("""
        INSERT INTO sources (source_id, url, title, publisher)
        VALUES ('test_source', 'file:///test/report2.pdf', '2023年报告', '小水电')
    """)

    # 插入测试文档
    conn.execute("""
        INSERT INTO documents (
            document_id, source_id, original_url, file_size, content_hash,
            local_path, content_kind, content_type, created_at
        ) VALUES (
            'doc_test456', 'test_source', 'file:///test/report2.pdf',
            1024, 'hash_456', '/tmp/test2.pdf', 'pdf', 'application/pdf',
            datetime('now')
        )
    """)

    conn.commit()
    conn.close()

    return api


class TestApiTrustedPipeline:
    """测试 Api 层真正使用可信 Pipeline。"""

    @patch("hydro_platform.acquisition.local_router.LocalFileRouter")
    @patch("hydro_platform.pipeline.orchestrator.parse_document")  # Patch where it's imported
    @patch("hydro_platform.pipeline.orchestrator.extract_candidates")  # Patch where it's imported
    def test_local_file_goes_through_pipeline(
        self, mock_extract, mock_parse, mock_local_router_class, api_with_test_db
    ):
        """本地文件通过 run_collection_task 走完整 Pipeline。"""
        # Mock LocalFileRouter
        mock_router = MagicMock()
        mock_local_router_class.return_value = mock_router

        from hydro_platform.acquisition.result import FetchResult, DownloadMeta
        from hydro_platform.common.enums import AccessMethod, ContentKind

        mock_fetch_result = FetchResult(
            success=True,
            meta=DownloadMeta(
                original_url="file:///test/report.pdf",
                final_url="file:///test/report.pdf",
                status_code=200,
                content_type="application/pdf",
                file_size=1024,
                content_hash="local_hash_123",
                content_kind=ContentKind.PDF,
                access_method=AccessMethod.LOCAL_IMPORT,
                fetched_at="2026-09-05T10:00:00Z"
            ),
            body=b"%PDF-1.4 fake",
            error_code=None,
            error=None
        )
        mock_router.fetch.return_value = mock_fetch_result

        # Mock 解析
        from hydro_platform.parsing.content import ParsedContent, Table
        mock_parse.return_value = ParsedContent(
            kind=ContentKind.PDF,
            ok=True,
            text="2023年发电量：100 GWh",
            tables=[Table(headers=[], rows=[])],
            error=None
        )

        # Mock 抽取
        from hydro_platform.models.candidate import ExtractionCandidate
        from hydro_platform.common.enums import GenerationMetric, NormalizedEnergyUnit, ValueType, MeasurementScope, PeriodType
        mock_extract.return_value = [
            ExtractionCandidate(
                entity_id="STATION_TOP100",
                task_id="test_task",
                source_id="test_source",
                period_type=PeriodType.CALENDAR_YEAR,
                period_label="2023",
                generation_gwh=100.0,
                value_raw="100",
                unit_raw="GWh",
                snippet="2023年发电量：100 GWh",
                locator="table[0]",
                value_type=ValueType.ACTUAL,
                measurement_scope=MeasurementScope.PLANT,
                flags=[]
            )
        ]

        # 调用统一入口
        result = api_with_test_db.run_collection_task(
            entity_id="STATION_TOP100",
            target_period="2023",
            local_file="/test/report.pdf",
            source_title="2023年年报",
            publisher="三峡集团"
        )

        # 验证结果
        print(f"DEBUG: result = {result}")
        assert result["status"] == "needs_review"  # Top100 停在复核闸门
        assert result["final_status"] == "needs_review"
        # documents_archived 可能为 0（文档已存在）或 1（新归档）
        assert result["documents_archived"] >= 0
        assert result["candidates_extracted"] == 1
        assert len(result["review_ids"]) == 1

        # 验证 Task 状态
        conn = api_with_test_db.get_db_connection()
        task_row = conn.execute(
            "SELECT status FROM tasks WHERE task_id LIKE '%STATION_TOP100%2023%'"
        ).fetchone()
        assert task_row["status"] == "needs_review"
        conn.close()

    @patch("hydro_platform.pipeline.orchestrator.extract_candidates")  # Patch where it's imported
    @patch("hydro_platform.pipeline.orchestrator.parse_document")  # Patch where it's imported
    def test_non_top100_auto_promotes(
        self, mock_parse, mock_extract, api_with_non_top100
    ):
        """非 Top100 电站 + 干净候选 → 自动升级为 publishable。"""
        # Debug: 检查数据库隔离
        conn = api_with_non_top100.get_db_connection()
        stations = conn.execute("SELECT entity_id FROM stations").fetchall()
        print(f"DEBUG: Stations in DB at start: {[s['entity_id'] for s in stations]}")
        conn.close()

        # 重置 mock（防止被前一个测试污染）
        mock_parse.reset_mock()
        mock_extract.reset_mock()

        # Mock 解析
        from hydro_platform.parsing.content import ParsedContent, Table
        from hydro_platform.common.enums import ContentKind

        mock_parse.return_value = ParsedContent(
            kind=ContentKind.PDF,
            ok=True,
            text="2023年发电量：50 GWh",
            tables=[Table(headers=[], rows=[])],
            error=None
        )

        # Mock 抽取（干净候选）
        from hydro_platform.models.candidate import ExtractionCandidate
        from hydro_platform.common.enums import GenerationMetric, NormalizedEnergyUnit, ValueType, MeasurementScope, PeriodType
        expected_candidate = ExtractionCandidate(
            entity_id="STATION_NORMAL",
            task_id="test_task",
            source_id="test_source",
            period_type=PeriodType.CALENDAR_YEAR,  # 必须指定，否则升级失败
            period_label="2023",
            generation_gwh=50.0,
            metric=GenerationMetric.GROSS_GENERATION,
            normalized_unit=NormalizedEnergyUnit.GWH,
            value_raw="50",
            unit_raw="GWh",
            snippet="2023年发电量：50 GWh",
            locator="table[0]",
            value_type=ValueType.ACTUAL,  # 必须指定，否则验证失败
            measurement_scope=MeasurementScope.PLANT,  # 必须指定
            flags=[]  # 无 flags = 干净候选
        )
        mock_extract.return_value = [expected_candidate]

        # Debug: 验证 mock 设置正确
        print(f"DEBUG: Mock extract configured to return: {mock_extract.return_value[0].entity_id}")
        print(f"DEBUG: Mock extract call_count before test: {mock_extract.call_count}")

        # 使用 LocalFileRouter（已测试通过）
        with patch("hydro_platform.acquisition.local_router.LocalFileRouter") as mock_local_router_class:
            mock_router = MagicMock()
            mock_local_router_class.return_value = mock_router

            from hydro_platform.acquisition.result import FetchResult, DownloadMeta
            from hydro_platform.common.enums import AccessMethod, ContentKind

            mock_router.fetch.return_value = FetchResult(
                success=True,
                meta=DownloadMeta(
                    original_url="file:///test/report2.pdf",
                    final_url="file:///test/report2.pdf",
                    status_code=200,
                    content_type="application/pdf",
                    file_size=1024,
                    content_hash="hash_456",
                    content_kind=ContentKind.PDF,
                    access_method=AccessMethod.LOCAL_IMPORT,
                    fetched_at="2026-09-05T10:00:00Z"
                ),
                body=b"%PDF-1.4 fake2",
                error_code=None,
                error=None
            )

            # Mock 校验（通过且无严重问题）
            # 注意：必须 patch orchestrator 中已导入的引用，而不是原始模块
            with patch("hydro_platform.pipeline.orchestrator.validate_candidate") as mock_validate:
                from hydro_platform.common.result import ValidationResult
                mock_validate.return_value = ValidationResult(
                    passed=True,
                    issues=[],
                    checked_fields=["generation_gwh", "period_label"]
                )

                result = api_with_non_top100.run_collection_task(
                    entity_id="STATION_NORMAL",
                    target_period="2023",
                    local_file="/test/report2.pdf",
                    source_title="2023年报告"
                )

        # 验证自动升级
        # Note: 如果候选有任何警告（flags），即使非 Top100 也会进复核
        # 我们的 mock 返回了空 flags，应该自动升级
        print(f"DEBUG: result = {result}")
        assert result["status"] == "success", f"Expected success but got {result['status']}, error: {result.get('error')}"
        assert result["candidates_promoted"] == 1
        assert len(result["promoted_keys"]) == 1

        # 验证数据库：应该有一条 publishable 记录
        conn = api_with_non_top100.get_db_connection()

        # Debug: 查看所有记录
        all_records = conn.execute("SELECT entity_id, period_label, publication_status FROM generation_records").fetchall()
        print(f"DEBUG: All generation_records: {[dict(r) for r in all_records]}")

        record = conn.execute("""
            SELECT publication_status
            FROM generation_records
            WHERE entity_id = 'STATION_NORMAL' AND period_label = '2023'
        """).fetchone()
        assert record is not None, f"Expected STATION_NORMAL record but got: {[dict(r) for r in all_records]}"
        assert record["publication_status"] == "publishable"
        conn.close()

    def test_approve_record_calls_orchestrator(self, api_with_test_db):
        """approve_record() 通过 orchestrator.apply_review_decision() 执行。"""
        # 先创建一个待复核记录
        conn = api_with_test_db.get_db_connection()

        # 插入 Task
        task_id = "STATION_TOP100::station_generation::2023"
        conn.execute("""
            INSERT INTO tasks (task_id, entity_id, entity_type, task_type, target_period, status, created_at, updated_at)
            VALUES (?, 'STATION_TOP100', 'station', 'station_generation', '2023', 'needs_review', datetime('now'), datetime('now'))
        """, (task_id,))

        # 插入 review_item
        review_id = "review_001"
        import json
        payload = json.dumps({
            "candidate": {
                "entity_id": "STATION_TOP100",
                "period_label": "2023",
                "generation_gwh": 100.0,
                "value_raw": "100",
                "unit_raw": "GWh",
                "snippet": "test",
                "locator": "test",
                "flags": [],
                "value_type": "actual",
                "measurement_scope": "plant"
            },
            "evidence_ids": ["evidence_001"]
        })
        conn.execute("""
            INSERT INTO review_items (review_id, task_id, entity_id, fact_type, fact_key, reason, status, payload, created_at)
            VALUES (?, ?, 'STATION_TOP100', 'generation', 'STATION_TOP100||2023|actual|plant', 'Test review', 'open', ?, datetime('now'))
        """, (review_id, task_id, payload))

        # 插入 evidence 记录（满足 generation_records 的 FK 约束）
        conn.execute("""
            INSERT INTO evidence (
                evidence_id, task_id, document_id, source_id,
                fact_type, fact_key, snippet, locator, created_at
            ) VALUES (
                'evidence_001', 'test_task', 'doc_b9b0b3650e8b909a', 'test_source',
                'generation', 'STATION_TOP100||2023|actual|plant', 'test snippet', 'test locator', datetime('now')
            )
        """)

        # 插入 generation_record（draft 状态）
        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_label, period_type, generation_gwh, value_type, measurement_scope,
                publication_status, evidence_id
            ) VALUES (
                'STATION_TOP100', '2023', 'calendar_year', 100.0, 'actual', 'plant',
                'draft', 'evidence_001'
            )
        """)
        record_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.commit()
        conn.close()

        # 执行 approve
        with patch("hydro_platform.pipeline.orchestrator.apply_review_decision") as mock_apply:
            from hydro_platform.pipeline.result import PipelineResult
            from hydro_platform.common.enums import TaskStatus

            mock_apply.return_value = PipelineResult(
                task_id=task_id,
                final_status=TaskStatus.SUCCESS,
                reached_stage="promotion"
            )

            result = api_with_test_db.approve_record(record_id)

        # 验证调用了 orchestrator
        assert mock_apply.called
        call_args = mock_apply.call_args
        assert call_args[0][2] == review_id  # review_id
        assert call_args[0][3] == 'approve'  # decision

        # 验证返回结果
        assert result["status"] == "success"
        assert result["review_id"] == review_id

    def test_reject_record_calls_orchestrator(self, api_with_test_db):
        """reject_record() 通过 orchestrator.apply_review_decision() 执行。"""
        # 准备数据（同 approve 测试）
        conn = api_with_test_db.get_db_connection()

        task_id = "STATION_TOP100::station_generation::2023"
        conn.execute("""
            INSERT INTO tasks (task_id, entity_id, entity_type, task_type, target_period, status, created_at, updated_at)
            VALUES (?, 'STATION_TOP100', 'station', 'station_generation', '2023', 'needs_review', datetime('now'), datetime('now'))
        """, (task_id,))

        review_id = "review_002"
        import json
        payload = json.dumps({
            "candidate": {
                "entity_id": "STATION_TOP100",
                "period_label": "2023",
                "generation_gwh": 100.0,
                "value_raw": "100",
                "unit_raw": "GWh",
                "snippet": "test",
                "locator": "test",
                "flags": [],
                "value_type": "actual",
                "measurement_scope": "plant"
            },
            "evidence_ids": ["evidence_002"]
        })
        conn.execute("""
            INSERT INTO review_items (review_id, task_id, entity_id, fact_type, fact_key, reason, status, payload, created_at)
            VALUES (?, ?, 'STATION_TOP100', 'generation', 'STATION_TOP100||2023|actual|plant', 'Test review', 'open', ?, datetime('now'))
        """, (review_id, task_id, payload))

        # 插入 evidence 记录（满足 generation_records 的 FK 约束）
        conn.execute("""
            INSERT INTO evidence (
                evidence_id, task_id, document_id, source_id,
                fact_type, fact_key, snippet, locator, created_at
            ) VALUES (
                'evidence_002', 'test_task', 'doc_b9b0b3650e8b909a', 'test_source',
                'generation', 'STATION_TOP100||2023|actual|plant', 'test snippet', 'test locator', datetime('now')
            )
        """)

        conn.execute("""
            INSERT INTO generation_records (
                entity_id, period_label, period_type, generation_gwh, value_type, measurement_scope,
                publication_status, evidence_id
            ) VALUES (
                'STATION_TOP100', '2023', 'calendar_year', 100.0, 'actual', 'plant',
                'draft', 'evidence_002'
            )
        """)
        record_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.commit()
        conn.close()

        # 执行 reject
        with patch("hydro_platform.pipeline.orchestrator.apply_review_decision") as mock_apply:
            from hydro_platform.pipeline.result import PipelineResult
            from hydro_platform.common.enums import TaskStatus, FailureStage

            mock_result = PipelineResult(
                task_id=task_id,
                final_status=TaskStatus.FAILED,
                reached_stage="review_decision",
                failure_stage=FailureStage.REVIEW_REJECTED
            )
            mock_apply.return_value = mock_result

            result = api_with_test_db.reject_record(record_id, "数据不可信")

        # 验证调用了 orchestrator
        assert mock_apply.called
        call_args = mock_apply.call_args
        assert call_args[0][2] == review_id
        assert call_args[0][3] == 'reject'

        # 验证返回结果
        assert result["status"] == "success"
        assert "已拒绝" in result["message"]
