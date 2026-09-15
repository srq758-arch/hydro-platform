"""验证 API 以 review_id 为复核操作主键。"""

from __future__ import annotations

import json
import base64
from io import BytesIO
import uuid

import pytest

from hydro_platform.app.api import Api
from hydro_platform.common.clock import now_iso


def test_api_review_detail_uses_review_id(monkeypatch, tmp_path):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path))
    api = Api(data_mode="test")
    api.initialize()
    conn = api.get_db_connection()
    now = now_iso()
    entity_id = "station-review-api"
    source_id = "source-review-api"
    document_id = "doc-review-api"
    candidate_id = "candidate-review-api"
    evidence_id = "evidence-review-api"
    review_id = "review-api-primary-key"
    pytest.importorskip("fitz")
    from pypdf import PdfWriter

    pdf_path = tmp_path / "report.pdf"
    pdf_stream = BytesIO()
    pdf_writer = PdfWriter()
    pdf_writer.add_blank_page(width=300, height=300)
    pdf_writer.add_blank_page(width=300, height=300)
    pdf_writer.write(pdf_stream)
    pdf_path.write_bytes(pdf_stream.getvalue())

    conn.execute(
        "INSERT INTO stations(entity_id, canonical_name, country) VALUES (?, ?, ?)",
        (entity_id, "Review API Station", "CN"),
    )
    conn.execute(
        "INSERT INTO sources(source_id, url, title, retrieved_at) VALUES (?, ?, ?, ?)",
        (source_id, "https://example.test/report", "Test report", now),
    )
    conn.execute(
        """INSERT INTO documents
        (document_id, source_id, original_url, content_kind, content_type,
         file_size, content_hash, local_path, fetched_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (document_id, source_id, "https://example.test/report", "report",
         "application/pdf", pdf_path.stat().st_size, "hash-review-api", str(pdf_path), now, now),
    )
    conn.execute(
        """INSERT INTO extraction_candidates
        (candidate_id, entity_id, document_id, period_type, period_label,
         value_type, measurement_scope, generation_gwh, value_raw, unit_raw,
         snippet, extraction_method, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (candidate_id, entity_id, document_id, "calendar_year", "2024",
         "actual", "plant", 12.5, "12.5", "GWh", "12.5 GWh", "rule", now),
    )
    conn.execute(
        """INSERT INTO evidence
        (evidence_id, source_id, document_id, content_hash, fact_type, fact_key,
         snippet, page_number, locator, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (evidence_id, source_id, document_id, "hash-review-api", "generation",
         f"{entity_id}:2024:actual", "12.5 GWh", 2, "page[2].ocr", now),
    )
    conn.execute(
        "INSERT INTO candidate_evidence(candidate_id, evidence_id) VALUES (?, ?)",
        (candidate_id, evidence_id),
    )
    payload = json.dumps({
        "candidate": {
            "candidate_id": candidate_id,
            "entity_id": entity_id,
            "document_id": document_id,
            "period_type": "calendar_year",
            "period_label": "2024",
            "value_type": "actual",
            "measurement_scope": "plant",
            "generation_gwh": 12.5,
            "value_raw": "12.5",
            "unit_raw": "GWh",
            "flags": ["OCR_DERIVED"],
        },
        "evidence_ids": [evidence_id],
        "evidence_metadata": {
            "ocr": {
                "page_number": 2,
                "engine": "fake-ocr",
                "engine_version": "test-1",
                "language": "eng",
                "region": {"x0": 0, "y0": 0, "x1": 100, "y1": 80},
                "source_image_sha256": "abc123",
            }
        },
    })
    conn.execute(
        """INSERT INTO review_items
        (review_id, entity_id, fact_type, fact_key, reason, status, payload,
         created_at, candidate_id)
        VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
        (review_id, entity_id, "generation", f"{entity_id}:2024:actual",
         "test", payload, now, candidate_id),
    )
    conn.commit()
    conn.close()

    detail = api.get_review_detail(review_id)
    assert detail is not None
    assert detail["id"] == review_id
    assert detail["review_id"] == review_id
    assert detail["candidate_id"] == candidate_id
    assert detail["evidences"][0]["evidence_id"] == evidence_id
    assert detail["page_number"] == 2
    assert detail["locator"] == "page[2].ocr"
    assert detail["candidate_flags"] == ["OCR_DERIVED"]
    assert detail["evidence_metadata"]["ocr"]["engine"] == "fake-ocr"
    assert detail["evidence_metadata"]["ocr"]["source_image_sha256"] == "abc123"
    preview = api.get_review_ocr_preview(review_id)
    assert preview["status"] == "success"
    assert preview["page_number"] == 2
    assert preview["region_highlighted"] is True
    assert preview["region"]["x1"] == 100
    assert base64.b64decode(preview["image_data"].split(",", 1)[1]).startswith(b"\x89PNG")
