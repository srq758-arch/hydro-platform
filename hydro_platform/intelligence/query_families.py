"""受控的搜索查询族与失败驱动改写。

查询词是搜索意图，不是来源或事实。这里的规则只生成有限、可审计的
检索表达；URL 仍只能来自真实搜索 provider，候选仍必须经过统一预检和
相关性门槛。失败改写最多触发一次，避免网络失败被放大成无限搜索。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from .deepseek_agent import TaskIntent


@dataclass(frozen=True)
class QueryVariant:
    """一条带来源族和理由的受控查询。"""

    query: str
    family: str
    rationale: str

    def to_dict(self) -> dict[str, str]:
        return {
            "query": self.query,
            "family": self.family,
            "rationale": self.rationale,
        }


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _names(station: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("local_name", "canonical_name"):
        value = _clean(station.get(key))
        if value and value not in values:
            values.append(value)
    aliases = station.get("aliases") or station.get("search_aliases") or ()
    if isinstance(aliases, str):
        aliases = re.split(r"[;,；、]", aliases)
    for alias in aliases:
        value = _clean(alias)
        if value and value not in values:
            values.append(value)
    return values


class QueryFamilyPlanner:
    """生成固定优先级的报告/公告查询族。"""

    @staticmethod
    def variants(
        *,
        station: dict[str, Any],
        target_period: str,
        metric: str = "generation",
        verified_domains: Iterable[str] = (),
        limit: int = 3,
    ) -> tuple[QueryVariant, ...]:
        year = _clean(target_period)
        name_values = _names(station)
        name = name_values[0] if name_values else _clean(station.get("canonical_name"))
        canonical = name_values[-1] if name_values else name
        operator = _clean(station.get("operator") or station.get("owner"))
        chinese = bool(re.search(r"[\u4e00-\u9fff]", name))
        variants: list[QueryVariant] = []
        if metric == "capacity":
            variants.extend((
                QueryVariant(
                    f'"{name}" {year} installed capacity MW',
                    "station_capacity",
                    "电站名+目标年+装机容量",
                ),
                QueryVariant(
                    f'"{canonical}" {year} capacity report',
                    "capacity_report",
                    "标准名+目标年+容量报告",
                ),
            ))
        elif chinese:
            variants.extend((
                QueryVariant(
                    f"{name} {year} 完成发电量",
                    "station_annual_generation",
                    "电站简称+目标年+完成发电量",
                ),
                QueryVariant(
                    f"{name} {year} 全年 发电量",
                    "station_full_year_generation",
                    "电站简称+目标年+全年口径",
                ),
            ))
            if operator:
                variants.append(QueryVariant(
                    f"{operator} {year} 发电量完成情况公告",
                    "operator_annual_disclosure",
                    "运营主体+目标年+发电量完成情况公告",
                ))
            else:
                variants.append(QueryVariant(
                    f"{name} {year} 发电量 年度报告",
                    "annual_report_index",
                    "电站简称+目标年+年度报告索引",
                ))
        else:
            is_portuguese = _clean(station.get("country")).lower() in {"brazil", "brasil", "portugal"}
            if is_portuguese:
                portuguese_name = re.sub(
                    r"^(?:usina\s+hidrel[eé]trica|central\s+hidrel[eé]trica)\s+",
                    "", name, flags=re.I,
                ).strip() or name
                variants.extend((
                    QueryVariant(
                        f'{portuguese_name} {year} geração anual',
                        "station_annual_generation",
                        "电站名+目标年+葡语全年发电量",
                    ),
                    QueryVariant(
                        f'{portuguese_name} {year} relatório anual geração',
                        "annual_report_index",
                        "电站名+目标年+葡语年度报告",
                    ),
                ))
            else:
                variants.extend((
                    QueryVariant(
                        f'"{name}" {year} annual generation',
                        "station_annual_generation",
                        "电站名+目标年+全年发电量",
                    ),
                    QueryVariant(
                        f'"{canonical}" {year} annual report generation',
                        "annual_report_index",
                        "标准名+目标年+年度报告",
                    ),
                ))
            if operator:
                if is_portuguese:
                    variants.append(QueryVariant(
                        f'{operator} {year} geração {portuguese_name}',
                        "operator_annual_disclosure",
                        "运营主体+目标年+葡语年度披露",
                    ))
                else:
                    variants.append(QueryVariant(
                        f'"{operator}" {year} annual report "{name}" generation',
                        "operator_annual_disclosure",
                        "运营主体+目标年+年度披露",
                    ))
        for domain in verified_domains:
            domain = _clean(domain).lower().removeprefix("www.")
            if not domain:
                continue
            if metric == "capacity":
                variants.append(QueryVariant(
                    f'site:{domain} "{name}" {year} capacity report',
                    "verified_site_report_index",
                    "已验证官网+报告索引",
                ))
            else:
                variants.append(QueryVariant(
                    f'site:{domain} "{name}" {year} annual generation',
                    "verified_site_report_index",
                    "已验证官网+年度发电量",
                ))
        seen: set[str] = set()
        output: list[QueryVariant] = []
        for variant in variants:
            query = _clean(variant.query)
            if not query or query in seen:
                continue
            seen.add(query)
            output.append(QueryVariant(query, variant.family, variant.rationale))
            if len(output) >= max(1, min(int(limit), 5)):
                break
        return tuple(output)

    @staticmethod
    def rewrite_after_failure(
        *,
        intent: TaskIntent,
        station: dict[str, Any],
        attempted_queries: Iterable[str],
        failure_code: str,
        verified_domains: Iterable[str] = (),
        limit: int = 2,
    ) -> tuple[QueryVariant, ...]:
        """按失败原因生成一次补充查询；网络故障不盲目扩大请求。"""
        code = _clean(failure_code).lower()
        network_failure = any(token in code for token in (
            "timeout", "429", "captcha", "验证码", "waf", "dns", "tls", "不可用",
        ))
        if network_failure:
            return ()
        attempted = {_clean(item) for item in attempted_queries if _clean(item)}
        if any(token in code for token in ("irrelevant", "ineligible", "无关", "不相关")):
            families = QueryFamilyPlanner.variants(
                station=station,
                target_period=intent.target_period,
                metric=intent.metric,
                verified_domains=verified_domains,
                limit=5,
            )
            preferred = ("operator_annual_disclosure", "annual_report_index", "verified_site_report_index")
            families = tuple(item for item in families if item.family in preferred)
        else:
            name = _names(station)
            display = name[0] if name else _clean(station.get("canonical_name"))
            year = _clean(intent.target_period)
            if intent.metric == "capacity":
                families = (
                    QueryVariant(f'"{display}" {year} filetype:pdf installed capacity', "capacity_pdf", "空结果后的 PDF 容量报告改写"),
                    QueryVariant(f'"{display}" {year} official capacity data', "capacity_official", "空结果后的官方容量数据改写"),
                )
            elif re.search(r"[\u4e00-\u9fff]", display):
                families = (
                    QueryVariant(f"{display} {year} 年度报告 发电量", "annual_report_index", "空结果后的年度报告索引改写"),
                    QueryVariant(f"{display} {year} 公告 全年 发电量 pdf", "annual_pdf_disclosure", "空结果后的公告 PDF 改写"),
                )
            else:
                families = (
                    QueryVariant(f'"{display}" {year} annual generation filetype:pdf', "annual_pdf_disclosure", "空结果后的年度 PDF 改写"),
                    QueryVariant(f'"{display}" {year} operating statistics report', "operating_statistics", "空结果后的运营统计改写"),
                )
        output = tuple(item for item in families if item.query not in attempted)
        return output[:max(1, min(int(limit), 2))]
