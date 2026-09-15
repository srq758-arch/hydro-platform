"""Structural contract for the provisional Development/Holdout split."""

import json
from pathlib import Path


def test_v5_2_manifest_has_disjoint_15_plus_5_split():
    root = Path(__file__).parent
    manifest = json.loads(
        (root / "manifests" / "v5_2_station_generation_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    cases = json.loads(
        (root / "ground_truth" / "station_generation_cases.json").read_text(
            encoding="utf-8"
        )
    )
    known_ids = {case["case_id"] for case in cases}
    development = set(manifest["development_case_ids"])
    holdout = set(manifest["holdout_case_ids"])

    assert len(development) == 15
    assert len(holdout) == 5
    assert development.isdisjoint(holdout)
    assert development | holdout <= known_ids
    assert manifest["acceptance_ready"] is False


def test_verified_development_cases_have_full_semantics_and_direct_documents():
    root = Path(__file__).parent
    cases = json.loads(
        (root / "ground_truth" / "development_verified_v1.json").read_text(encoding="utf-8")
    )
    assert len(cases) == 4
    for case in cases:
        assert case["metric"] == "gross_generation"
        assert case["period_type"] == "calendar_year"
        assert case["measurement_scope"] == "plant"
        assert case["value_type"] == "actual"
        assert case["expected_unit"] == "gwh"
        assert case["source_url"].lower().endswith(".pdf")
        assert case["evidence_locator"]


def test_holdout_inputs_do_not_expose_expected_values_or_evidence_urls():
    root = Path(__file__).parent
    cases = json.loads(
        (root / "ground_truth" / "holdout_inputs_v1.json").read_text(encoding="utf-8")
    )
    assert len(cases) == 5
    for case in cases:
        assert "expected_generation_gwh" not in case
        assert "source_url" not in case
        assert "evidence_locator" not in case
