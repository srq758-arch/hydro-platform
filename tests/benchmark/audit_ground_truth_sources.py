"""Bounded live audit for Ground Truth source URLs.

This is an explicit network diagnostic, not part of the default pytest suite.
It uses the application's UrlProbe and writes only status/feature metadata;
page content is neither archived nor copied into the report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from hydro_platform.discovery.url_probe import UrlProbe


GENERATION_TERMS = (
    "发电量", "总发电量", "generation", "generated", "electricity production"
)
GENERIC_NAME_TERMS = {
    "dam", "hydroelectric", "hydropower", "plant", "station", "generating",
}


def _name_terms(name: str) -> list[str]:
    return [
        token.casefold() for token in name.replace("-", " ").split()
        if len(token) >= 4 and token.casefold() not in GENERIC_NAME_TERMS
    ]


def classify(case: dict, probe: dict) -> dict:
    preview = str((probe.get("metadata") or {}).get("content_preview") or "")
    preview_folded = preview.casefold()
    parsed = urlparse(probe.get("final_url") or case["source_url"])
    path = parsed.path.rstrip("/").casefold()
    homepage_like = path in ("", "/en", "/cn", "/zh", "/english")
    year_match = str(case["year"]) in preview_folded
    metric_match = any(term.casefold() in preview_folded for term in GENERATION_TERMS)
    terms = _name_terms(case["canonical_name"])
    entity_match = any(term in preview_folded for term in terms) if terms else False

    if probe.get("access_status") not in ("reachable", "requires_browser"):
        evidence_status = "inaccessible"
    elif homepage_like:
        evidence_status = "homepage_not_evidence"
    elif year_match and metric_match and entity_match:
        evidence_status = "direct_evidence_candidate"
    else:
        evidence_status = "reachable_but_unverified"

    return {
        "case_id": case["case_id"],
        "canonical_name": case["canonical_name"],
        "year": case["year"],
        "source_url": case["source_url"],
        "final_url": probe.get("final_url"),
        "access_status": probe.get("access_status"),
        "http_status": probe.get("http_status"),
        "error": probe.get("error"),
        "homepage_like": homepage_like,
        "preview_length": len(preview),
        "entity_match": entity_match,
        "year_match": year_match,
        "metric_match": metric_match,
        "evidence_status": evidence_status,
    }


def run(cases_path: Path, output_json: Path, output_md: Path) -> list[dict]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    probes = UrlProbe(timeout=15.0).probe_many(
        [
            {
                "url": case["source_url"],
                "metadata": {"case_id": case["case_id"]},
            }
            for case in cases
        ],
        max_workers=4,
    )
    results = [classify(case, probe) for case, probe in zip(cases, probes)]
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for item in results:
        status = item["evidence_status"]
        counts[status] = counts.get(status, 0) + 1
    lines = [
        "# Ground Truth 来源实时审计",
        "",
        "该报告由程序自身 UrlProbe 实际联网产生。可访问只表示 URL 可打开，",
        "不等于其能够证明目标电站、目标年份和年度总发电量。",
        "",
        "## 汇总",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(counts.items()))
    lines.extend([
        "",
        "## 明细",
        "",
        "| Case | 电站 | 年份 | HTTP | 访问 | 证据判定 |",
        "|---|---|---:|---:|---|---|",
    ])
    for item in results:
        lines.append(
            f"| {item['case_id']} | {item['canonical_name']} | {item['year']} | "
            f"{item['http_status'] or '-'} | {item['access_status']} | {item['evidence_status']} |"
        )
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    results = run(args.cases, args.json, args.markdown)
    for item in results:
        print(
            f"{item['case_id']} {item['http_status'] or '-'} "
            f"{item['access_status']} {item['evidence_status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
