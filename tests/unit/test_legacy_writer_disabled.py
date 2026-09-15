"""旧正式数据写入路径必须保持关闭。"""

import sqlite3

import pytest

from hydro_platform.app.api import Api
from hydro_platform.app.writer import RecordWriter
from hydro_platform.pipeline.approval_transaction import ApprovalTransaction
from hydro_platform.pipeline.candidate_evidence_binding import (
    CandidateEvidenceError,
    promote_candidate_to_generation_record,
)


def test_legacy_record_writer_cannot_write_generation_records():
    writer = RecordWriter(sqlite3.connect(":memory:"))

    with pytest.raises(RuntimeError, match="禁止绕过"):
        writer.save_candidates([], "doc-1", "src-1")


def test_legacy_api_entry_is_disabled_before_opening_database():
    api = Api(data_mode="test")

    with pytest.raises(RuntimeError, match="旧候选写入入口已禁用"):
        api._legacy_save_candidates_to_database([], "doc-1", "src-1")


def test_candidate_binding_legacy_promotion_is_disabled():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(CandidateEvidenceError, match="旧候选升级入口已禁用"):
        promote_candidate_to_generation_record(conn, "candidate-1")


def test_approval_transaction_direct_writer_is_disabled():
    conn = sqlite3.connect(":memory:")
    manager = ApprovalTransaction(conn)
    with manager.atomic_approval("review-1", "task-1") as approval:
        with pytest.raises(RuntimeError, match="直写入口已禁用"):
            approval.promote_to_generation_records(
                entity_id="station-1",
                period_label="2024",
                generation_gwh=1.0,
                evidence_id="evidence-1",
            )
