"""可信出口必须验证 Candidate→Evidence→Document 完整链路。"""

from hydro_platform.common.clock import now_iso
from hydro_platform.app.queries import ReadQueries
from hydro_platform.products import GenerationRanking
from hydro_platform.products.trustworthy_filter import get_top_n_trustworthy


def _insert_valid_chain(db, prefix: str, *, candidate_id: str | None):
    entity_id = f"{prefix}_station"
    source_id = f"{prefix}_source"
    document_id = f"{prefix}_document"
    evidence_id = f"{prefix}_evidence"
    db.execute(
        "INSERT INTO stations (entity_id, entity_type, canonical_name, country) VALUES (?, 'station', ?, 'CN')",
        (entity_id, prefix),
    )
    db.execute(
        "INSERT INTO sources (source_id, url, title) VALUES (?, ?, ?)",
        (source_id, f"https://example.test/{prefix}", prefix),
    )
    db.execute(
        """INSERT INTO documents
           (document_id, source_id, original_url, file_size, content_hash,
            local_path, content_kind, created_at)
           VALUES (?, ?, ?, 10, ?, ?, 'html', ?)""",
        (document_id, source_id, f"https://example.test/{prefix}", f"hash-{prefix}", f"/tmp/{prefix}.html", now_iso()),
    )
    if candidate_id:
        db.execute(
            """INSERT INTO extraction_candidates
               (candidate_id, entity_id, document_id, period_type, period_label,
                value_type, measurement_scope, generation_gwh, extracted_at)
               VALUES (?, ?, ?, 'calendar_year', '2024', 'actual', 'plant', 100, ?)""",
            (candidate_id, entity_id, document_id, now_iso()),
        )
        db.execute(
            "UPDATE extraction_candidates SET metric='gross_generation', normalized_unit='gwh' WHERE candidate_id=?",
            (candidate_id,),
        )
    db.execute(
        """INSERT INTO evidence
           (evidence_id, source_id, document_id, content_hash, fact_type, fact_key, snippet, created_at)
           VALUES (?, ?, ?, ?, 'generation', ?, '2024 generation 100 GWh', ?)""",
        (evidence_id, source_id, document_id, f"hash-{prefix}", f"{entity_id}:2024", now_iso()),
    )
    if candidate_id:
        db.execute(
            "INSERT INTO candidate_evidence (candidate_id, evidence_id) VALUES (?, ?)",
            (candidate_id, evidence_id),
        )
    db.execute(
        """INSERT INTO generation_records
           (entity_id, period_type, period_label, generation_gwh, value_type,
            measurement_scope, evidence_id, candidate_id, validation_status,
            review_status, publication_status, confidence, metric, normalized_unit, created_at)
           VALUES (?, 'calendar_year', '2024', 100, 'actual', 'plant', ?, ?,
                   'passed', 'approved', 'publishable', .9, 'gross_generation', 'gwh', ?)""",
        (entity_id, evidence_id, candidate_id, now_iso()),
    )


def test_trustworthy_filter_requires_candidate_evidence_document_chain(db):
    _insert_valid_chain(db, "valid", candidate_id="valid_candidate")
    _insert_valid_chain(db, "broken", candidate_id=None)
    db.commit()

    rows = get_top_n_trustworthy(db, year="2024", n=100)

    assert [row["entity_id"] for row in rows] == ["valid_station"]
    assert db.execute("SELECT COUNT(*) FROM v_top100_generation").fetchone()[0] == 1


def test_trustworthy_filter_rejects_mismatched_candidate_binding(db):
    _insert_valid_chain(db, "mismatch", candidate_id="mismatch_candidate")
    db.execute(
        "UPDATE extraction_candidates SET generation_gwh = 999 WHERE candidate_id = ?",
        ("mismatch_candidate",),
    )
    db.commit()

    assert get_top_n_trustworthy(db, year="2024", n=100) == []


def test_product_pages_share_the_complete_trustworthy_chain(db):
    _insert_valid_chain(db, "valid_product", candidate_id="valid_product_candidate")
    _insert_valid_chain(db, "broken_product", candidate_id=None)
    _insert_valid_chain(db, "null_confidence", candidate_id="null_confidence_candidate")
    db.execute(
        "UPDATE generation_records SET confidence = NULL WHERE entity_id = ?",
        ("null_confidence_station",),
    )
    db.commit()

    queries = ReadQueries(db)
    dashboard = queries.get_dashboard()
    coverage = queries.get_data_coverage_stats()
    browse = queries.browse_records(year="2024", published_only=True)
    top100 = queries.get_top100()
    statistics = GenerationRanking(db).get_statistics(2024)

    assert dashboard["asset_cards"]["accepted_records"] == 1
    assert dashboard["quality"]["buckets"][0]["count"] == 1
    assert dashboard["coverage_by_year"] == [{"year": "2024", "accepted": 1}]
    assert coverage["overall"]["stations_with_data"] == 1
    assert coverage["overall"]["total_records"] == 1
    assert browse["total"] == 1
    assert [row["entity_id"] for row in browse["items"]] == ["valid_product_station"]
    assert [row["entity_id"] for row in top100] == ["valid_product_station"]
    assert statistics["total_records"] == 1
