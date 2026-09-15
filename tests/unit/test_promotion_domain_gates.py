from hydro_platform.common.enums import (
    GenerationMetric,
    MeasurementScope,
    NormalizedEnergyUnit,
    PeriodType,
    ValueType,
)
from hydro_platform.lifecycle.promotion_gates import (
    PROMOTION_GATE_VERSION,
    evaluate_station_annual_generation_gates,
)
from hydro_platform.models.candidate import ExtractionCandidate


def _candidate(**over):
    values = {
        "entity_id": "station-1",
        "period_type": PeriodType.CALENDAR_YEAR,
        "period_label": "2024",
        "metric": GenerationMetric.GROSS_GENERATION,
        "measurement_scope": MeasurementScope.PLANT,
        "value_type": ValueType.ACTUAL,
        "generation_gwh": 123.4,
        "unit_raw": "亿千瓦时",
        "normalized_unit": NormalizedEnergyUnit.GWH,
    }
    values.update(over)
    return ExtractionCandidate(**values)


def test_all_eight_gates_are_explicit_and_versioned():
    report = evaluate_station_annual_generation_gates(
        _candidate(), evidence_persisted=True, review_satisfied=True
    )
    assert report.passed
    assert [item.name for item in report.decisions] == [
        "entity", "period", "metric", "scope", "value_type", "unit", "evidence", "review"
    ]
    assert {item.version for item in report.decisions} == {PROMOTION_GATE_VERSION}


def test_confidence_cannot_override_failed_metric_gate():
    report = evaluate_station_annual_generation_gates(
        _candidate(metric=GenerationMetric.ENERGY_SENT_OUT, confidence=1.0),
        evidence_persisted=True,
        review_satisfied=True,
    )
    assert not report.passed
    assert [item.name for item in report.failures] == ["metric"]


def test_ytd_and_group_total_fail_independent_gates():
    report = evaluate_station_annual_generation_gates(
        _candidate(
            period_type=PeriodType.YEAR_TO_DATE,
            period_label="2024-YTD",
            measurement_scope=MeasurementScope.GROUP,
        ),
        evidence_persisted=True,
        review_satisfied=True,
    )
    assert {item.name for item in report.failures} == {"period", "scope"}


def test_period_gate_rejects_year_without_full_year_clue():
    cand = _candidate(flags=["PERIOD_UNCLEAR"])
    report = evaluate_station_annual_generation_gates(
        cand, evidence_persisted=True, review_satisfied=True
    )
    assert not report.passed
    assert [item.name for item in report.failures] == ["period"]
