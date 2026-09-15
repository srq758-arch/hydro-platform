"""B0 五层来源契约的结构与 lineage 行为。"""

import hashlib

import pytest
from pydantic import ValidationError

from hydro_platform.common.enums import (
    ContentKind,
    SourceAttemptStatus,
)
from hydro_platform.models.source_pipeline import (
    CandidateSource,
    EvidenceCandidate,
    EvidenceDocument,
    SearchLead,
    SourceAttempt,
)


SHA = hashlib.sha256(b"payload").hexdigest()


def test_five_layer_contract_keeps_parent_lineage_and_stable_ids():
    lead = SearchLead(
        task_id="task-1",
        provider="program_search",
        query="Three Gorges 2023 annual generation",
        url="https://example.test/result",
        rank=1,
    )
    same_lead = SearchLead(
        task_id="task-1",
        provider="program_search",
        query="Three Gorges 2023 annual generation",
        url="https://example.test/result",
        rank=1,
    )
    assert lead.lead_id == same_lead.lead_id

    source = CandidateSource(
        task_id="task-1",
        lead_id=lead.lead_id,
        url=lead.url,
        canonical_url=lead.url,
        discovery_method="program_search_result",
        expected_content_kind=ContentKind.ANY,
        priority_score=0.8,
    )
    attempt = SourceAttempt(
        task_id="task-1",
        candidate_source_id=source.candidate_source_id,
        attempt_no=1,
    )
    document = EvidenceDocument(
        document_id="doc-1",
        source_attempt_id=attempt.attempt_id,
        task_id="task-1",
        original_url=source.url,
        final_url=source.canonical_url,
        content_hash=SHA,
        file_size=7,
        content_kind=ContentKind.HTML,
        local_path="raw/doc-1.html",
    )
    candidate = EvidenceCandidate(
        candidate_id="cand-1",
        source_attempt_id=attempt.attempt_id,
        evidence_document_id=document.document_id,
        task_id="task-1",
        entity_id="station-1",
        fact_type="station_generation",
        fact_key="station-1:2023:gross_generation",
        payload_hash=SHA,
        extractor_version="rules-v1",
    )

    assert source.lead_id == lead.lead_id
    assert attempt.candidate_source_id == source.candidate_source_id
    assert document.source_attempt_id == attempt.attempt_id
    assert candidate.source_attempt_id == attempt.attempt_id
    assert candidate.evidence_document_id == document.document_id
    assert all(
        len(value) == 64
        for value in (source.lineage_hash, document.lineage_hash, candidate.lineage_hash)
    )


def test_successful_attempt_requires_document_and_failed_attempt_requires_reason():
    common = {
        "task_id": "task-1",
        "candidate_source_id": "src-1",
        "attempt_no": 1,
    }
    with pytest.raises(ValidationError, match="document_id"):
        SourceAttempt(**common, status=SourceAttemptStatus.SUCCEEDED)
    with pytest.raises(ValidationError, match="failure_code"):
        SourceAttempt(**common, status=SourceAttemptStatus.FAILED)

    succeeded = SourceAttempt(
        **common,
        status=SourceAttemptStatus.SUCCEEDED,
        document_id="doc-1",
    )
    failed = SourceAttempt(
        **common,
        status=SourceAttemptStatus.FAILED,
        failure_code="HTTP_404",
    )
    assert succeeded.document_id == "doc-1"
    assert failed.failure_code == "HTTP_404"


def test_evidence_hashes_must_be_sha256():
    with pytest.raises(ValidationError, match="64 位 SHA256"):
        EvidenceDocument(
            document_id="doc-1",
            source_attempt_id="attempt-1",
            task_id="task-1",
            original_url="https://example.test/a",
            final_url="https://example.test/a",
            content_hash="not-a-hash",
            file_size=1,
            content_kind=ContentKind.HTML,
            local_path="raw/a.html",
        )


def test_direct_candidate_source_does_not_require_search_lead():
    source = CandidateSource(
        task_id="task-1",
        url="https://operator.test/report.pdf",
        canonical_url="https://operator.test/report.pdf",
        discovery_method="user_confirmed_url",
    )
    assert source.lead_id is None
    assert source.candidate_source_id.startswith("src_")
