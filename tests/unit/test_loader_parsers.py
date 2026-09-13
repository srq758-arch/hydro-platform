"""loader 解析辅助函数单测：类型转换与 turbines 配置串求和。"""

from __future__ import annotations

import pytest

from hydro_platform.registry import loader


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", None),
        ("   ", None),
        (None, None),
        ("20", 20),
        ("32 x 700 MW; 2 x 50 MW", 34),
        ("16 x 1000 MW", 16),
        ("18 x 611 MW; 6 x 39 MW", 24),
        ("no digits here", None),
    ],
)
def test_parse_turbines(raw, expected):
    assert loader._parse_turbines(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("", None), ("  ", None), ("1990", 1990), ("1990.0", 1990), ("abc", None)],
)
def test_to_int(raw, expected):
    assert loader._to_int(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("", None), ("22500", 22500.0), ("30.5", 30.5), ("x", None)],
)
def test_to_float(raw, expected):
    assert loader._to_float(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("1", True), ("true", True), ("YES", True), ("0", False), ("", False), (None, False)],
)
def test_to_bool(raw, expected):
    assert loader._to_bool(raw) is expected


def test_clean_strips_and_nulls():
    assert loader._clean("  hi ") == "hi"
    assert loader._clean("   ") is None
    assert loader._clean(None) is None
