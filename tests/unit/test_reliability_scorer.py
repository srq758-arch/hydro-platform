"""来源可靠性评分的域名边界测试。"""

import pytest

from hydro_platform.reliability.scorer import ReliabilityScorer


def test_trusted_domain_matches_exact_host_and_subdomain():
    scorer = ReliabilityScorer()

    assert scorer.score_source_reliability("https://eia.gov/report") == 0.95
    assert scorer.score_source_reliability("https://www.eia.gov/report") == 0.95
    assert scorer.score_source_reliability("https://data.ctg.com.cn/report") == 0.90


def test_trusted_domain_substring_spoof_does_not_receive_trusted_score():
    scorer = ReliabilityScorer()

    spoofed = scorer.score_source_reliability(
        "https://eia.gov.example/report", source_type="reference"
    )
    assert spoofed < 0.95
    assert scorer.score_source_reliability(
        "https://not-ctg.com.cn.evil.example/report", source_type="reference"
    ) < 0.90


def test_government_and_organization_suffixes_require_domain_boundary():
    scorer = ReliabilityScorer()

    assert scorer.score_source_reliability(
        "https://energy.gov.cn/report", source_type="reference"
    ) == 0.62
    assert scorer.score_source_reliability(
        "https://research.org.br/report", source_type="reference"
    ) == pytest.approx(0.57)
    assert scorer.score_source_reliability(
        "https://energy.gov.example/report", source_type="reference"
    ) == 0.52
    assert scorer.score_source_reliability(
        "https://research.org.example/report", source_type="reference"
    ) == 0.52
