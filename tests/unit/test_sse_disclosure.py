"""SSE official disclosure discovery and seed/operator identity hints."""

from hydro_platform.intelligence.sse_disclosure import deterministic_issuer_hints


def test_three_gorges_seed_gets_deterministic_changjiang_power_issuer_hint():
    hints = deterministic_issuer_hints({
        "country": "China",
        "canonical_name": "Baihetan hydroelectric plant",
        "local_name": "金沙江白鹤滩水电站",
        "operator": "China Yangzi River Three Gorges Group",
    })

    assert hints == [{
        "security_code": "600900",
        "issuer_name": "中国长江电力股份有限公司",
        "issuer_source": "deterministic_operator_alias",
    }]


def test_unrelated_chinese_station_does_not_get_three_gorges_hint():
    assert deterministic_issuer_hints({
        "country": "China",
        "canonical_name": "Test Hydropower Plant",
        "local_name": "测试水电站",
        "operator": "Independent Hydropower Company",
    }) == []


def test_non_chinese_station_does_not_get_chinese_exchange_hint():
    assert deterministic_issuer_hints({
        "country": "Brazil",
        "canonical_name": "Itaipu hydroelectric plant",
        "operator": "Itaipu Binacional",
    }) == []
