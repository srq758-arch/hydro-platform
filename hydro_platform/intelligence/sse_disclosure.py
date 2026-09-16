"""上交所公开公告的受控发现通道。"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterable, Mapping

import requests


class SseDisclosureProvider:
    """只读取上交所公告目录，返回官方 PDF 候选，不写入任何正式数据。"""

    endpoint = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"

    def __init__(self, *, get: Callable[..., Any] = requests.get):
        self._get = get

    @staticmethod
    def _payload(text: str) -> dict[str, Any]:
        match = re.search(r"^[^(]*\((.*)\)\s*$", text.strip(), re.S)
        return json.loads(match.group(1) if match else text)

    def discover(self, *, issuers: Iterable[dict[str, str]], target_year: str) -> list[dict[str, Any]]:
        try:
            year = int(target_year)
        except (TypeError, ValueError):
            return []
        values: list[dict[str, Any]] = []
        for issuer in list(issuers)[:2]:
            code = str(issuer.get("security_code") or "")
            if not re.fullmatch(r"\d{6}", code):
                continue
            params = {
                "jsonCallBack": "hydroCallback", "isPagination": "true", "productId": code,
                "keyWord": "发电量完成情况", "securityType": "0101,120100,020100,020200,120200",
                "reportType": "ALL", "reportType2": "", "beginDate": f"{year}-01-01",
                "endDate": f"{year + 1}-01-31", "pageHelp.pageSize": "10", "pageHelp.pageNo": "1",
                "pageHelp.beginPage": "1", "pageHelp.cacheSize": "1", "pageHelp.endPage": "5",
            }
            try:
                response = self._get(self.endpoint, params=params, timeout=20, headers={
                    "User-Agent": "Mozilla/5.0 HydroPlatform/1.0 source-discovery",
                    "Referer": "https://www.sse.com.cn/",
                })
                response.raise_for_status()
                rows = self._payload(response.text).get("pageHelp", {}).get("data", [])
            except (requests.RequestException, ValueError, AttributeError, TypeError):
                continue
            for row in rows if isinstance(rows, list) else []:
                title = str(row.get("TITLE") or "")
                url_path = str(row.get("URL") or "")
                if f"{year}年" not in title or "发电量" not in title or not url_path.startswith("/"):
                    continue
                values.append({
                    "url": "https://www.sse.com.cn" + url_path,
                    "canonical_url": "https://www.sse.com.cn" + url_path,
                    "link_text": title,
                    "section_title": f"上海证券交易所 · {row.get('SECURITY_NAME') or code}",
                    "source_type": "official", "document_type": "pdf",
                    "discovery_method": "sse_official_disclosure",
                    "match_reason": "上交所公开披露目录命中；将以 PDF 正文核验电站、年份和全年口径",
                    "metadata": {
                        "issuer_name": issuer.get("issuer_name"), "security_code": code,
                        "issuer_source": issuer.get("issuer_source") or "model_or_user_hint",
                        "verify_pdf_text": True, "search_provider": "sse_official_disclosure",
                    },
                })
        return values


def deterministic_issuer_hints(station: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return audited exchange issuer hints for well-known Chinese operators.

    GEM seed rows often carry the English owner ``China Yangzi River Three Gorges
    Group`` while the Shanghai exchange disclosures are filed by ``长江电力``
    (600900).  DeepSeek may identify this relationship, but it is a stable
    identity mapping rather than a fact extracted from the web.  The returned
    value is only a directory query hint; the SSE title and PDF body remain the
    evidence gates.
    """
    country = str(station.get("country") or "").strip().lower()
    if country not in {"china", "中国", "cn"}:
        return []
    fields = " ".join(
        str(station.get(key) or "")
        for key in ("canonical_name", "local_name", "aliases", "operator", "owner")
    ).lower()
    three_gorges_markers = (
        "three gorges", "yangzi", "yangtze", "中国三峡", "长江电力", "长江三峡",
        "三峡", "白鹤滩", "溪洛渡", "乌东德", "向家坝",
    )
    if not any(marker in fields for marker in three_gorges_markers):
        return []
    return [{
        "security_code": "600900",
        "issuer_name": "中国长江电力股份有限公司",
        "issuer_source": "deterministic_operator_alias",
    }]
