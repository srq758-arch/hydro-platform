"""受控的运营主体检索提示。

这些映射只用于提高来源检索召回率，不代表事实值、所有权或正式数据来源。
候选仍必须经过原文访问、实体/年份/全年口径和单位校验。
"""

from __future__ import annotations

from typing import Any, Mapping


def deterministic_operator_hint(station: Mapping[str, Any]) -> str | None:
    """为缺少 operator/owner 的种子补充可审计的运营主体检索词。"""
    country = str(station.get("country") or "").strip().lower()
    fields = " ".join(
        str(station.get(key) or "")
        for key in ("canonical_name", "local_name", "aliases")
    ).lower()

    if country in {"china", "中国", "cn"} and any(
        marker in fields for marker in ("jinping-i", "锦屏一级", "锦屏一")
    ):
        return "雅砻江流域水电开发有限公司"

    if country in {"egypt", "مصر"} and any(
        marker in fields for marker in ("aswan high", "السد العالي", "aswan dam")
    ):
        return "Egyptian Electricity Holding Company"

    if country in {"turkey", "türkiye", "turkiye"} and any(
        marker in fields for marker in ("ataturk", "atatürk", "أتاتورك")
    ):
        return "Elektrik Üretim A.Ş. (EÜAŞ)"

    return None
