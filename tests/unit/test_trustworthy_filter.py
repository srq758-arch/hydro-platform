"""可信产品过滤器的硬门禁测试。"""

from hydro_platform.products.trustworthy_filter import TrustworthyFilter


def _record(**overrides):
    record = {
        "value_type": "actual",
        "period_type": "calendar_year",
        "measurement_scope": "plant",
        "metric": "gross_generation",
        "normalized_unit": "gwh",
        "validation_status": "passed",
        "publication_status": "publishable",
        "review_status": "approved",
        "evidence_id": "ev_1",
        "confidence": 0.9,
    }
    record.update(overrides)
    return record


def test_sql_filter_rejects_null_confidence():
    where, params = TrustworthyFilter.get_sql_where_clause(table_alias="g")

    assert "g.confidence >= ?" in where
    assert "confidence IS NULL OR" not in where
    assert params[-1] == TrustworthyFilter.DEFAULT_CONFIDENCE_THRESHOLD


def test_record_with_null_confidence_is_not_trustworthy():
    accepted, reasons = TrustworthyFilter.validate_record_trustworthy(
        _record(confidence=None)
    )

    assert not accepted
    assert any("confidence" in reason for reason in reasons)


def test_record_at_confidence_threshold_is_trustworthy():
    accepted, reasons = TrustworthyFilter.validate_record_trustworthy(
        _record(confidence=TrustworthyFilter.DEFAULT_CONFIDENCE_THRESHOLD)
    )

    assert accepted
    assert reasons == []
