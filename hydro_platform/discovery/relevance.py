"""候选来源的任务相关性校验。

来源域名可信或 URL 可打开，并不意味着页面可以用于某个电站某一年度的
发电量采集。本模块只对公开的标题、摘要、链接文字和可选页面预览做保守
判断；判断不充分时宁可不推荐，也绝不把背景新闻包装成可采集来源。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_GENERATION_TERMS = (
    "发电量", "上网电量", "年发电量", "年度发电", "electricity generation",
    "annual generation", "annual output", "generation gwh", "generation twh",
)
_ANNUAL_REPORT_TERMS = (
    "年度报告", "年报", "发电量完成情况公告", "annual report", "sustainability report", "esg report",
)
_ANNUAL_SCOPE_TERMS = (
    "全年", "全年度", "年度", "年内", "截至12月31日", "截至 12 月 31 日", "年度累计", "发电量完成情况公告",
    "annual", "full year", "year ended", "for the year",
)
_PARTIAL_SCOPE_TERMS = (
    "一季度", "二季度", "三季度", "四季度", "上半年", "下半年", "月度", "当月", "单月",
    "季度", "截至6月", "截至 6 月", "截至9月", "截至 9 月", "截至10月", "截至 10 月",
    "截至11月", "截至 11 月", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november",
)
_EXCLUSION_TERMS = (
    "安全责任", "责任人名单", "任命", "招标", "中标", "采购", "招聘",
    "design generation", "设计年发电量", "预计发电量", "预测发电量",
    "cumulative generation", "累计发电量",
)


@dataclass(frozen=True)
class RelevanceResult:
    eligible: bool
    score: float
    reason: str
    evidence: str
    period_scope: str = "unknown"


class CandidateRelevanceVerifier:
    """对来源候选执行与任务无关的硬过滤及可解释评分。"""

    @staticmethod
    def _aliases(station: dict) -> list[str]:
        raw = [
            station.get("canonical_name"), station.get("local_name"),
        ]
        aliases = station.get("aliases")
        if isinstance(aliases, str):
            raw.extend(re.split(r"[;,|/；、]", aliases))
        elif isinstance(aliases, Iterable):
            raw.extend(str(item) for item in aliases)
        # Identity Profile 的 search_aliases 由 seedlist 原字段派生或由已经
        # 接受/成功的来源画像补充；它不覆盖 canonical_name，只扩大可解释匹配。
        search_aliases = station.get("search_aliases")
        if isinstance(search_aliases, str):
            raw.extend(re.split(r"[;,|/；、]", search_aliases))
        elif isinstance(search_aliases, Iterable):
            raw.extend(str(item) for item in search_aliases)
        values: list[str] = []
        for value in raw:
            value = str(value or "").strip()
            if len(value) >= 3 and value not in values:
                values.append(value)

            # 名称库往往保留全称，而官方公告、证券披露和新闻摘要常使用简称。
            # 这里仅生成可追溯的去设施后缀/去常见河流前缀变体，不用模糊两字
            # 匹配，避免把“某某三峡”这类无关页面误认为同一电站。
            simplified = re.sub(
                r"\s+(?:dam\s+)?(?:hydroelectric|hydropower|power)\s+(?:plant|station)$",
                "", value, flags=re.I,
            ).strip(" -—")
            if len(simplified) >= 3 and simplified not in values:
                values.append(simplified)
            chinese_name = re.sub(r"^(?:长江|金沙江|雅砻江|澜沧江|黄河|珠江|红水河)", "", value)
            if len(chinese_name) >= 3 and chinese_name not in values:
                values.append(chinese_name)
            # “三峡水电站”和“三峡电站”是同一座电站的常见公开写法；保留
            # “电站”二字可以避免把仅提到“三峡”的泛背景资料放进来。
            short_station = re.sub(r"水电(?:站|厂)$", "电站", chinese_name)
            if len(short_station) >= 3 and short_station not in values:
                values.append(short_station)
        return values

    @staticmethod
    def _text(candidate: dict) -> str:
        metadata = candidate.get("metadata") or {}
        values = (
            candidate.get("url"), candidate.get("canonical_url"), candidate.get("final_url"),
            candidate.get("link_text"), candidate.get("section_title"), candidate.get("match_reason"),
            metadata.get("search_title"), metadata.get("search_snippet"),
            metadata.get("content_preview"), metadata.get("parent_content_preview"),
        )
        return " ".join(str(value or "") for value in values).lower()

    @staticmethod
    def _excerpt(text: str, terms: Iterable[str], width: int = 180) -> str:
        for term in terms:
            index = text.lower().find(term.lower())
            if index >= 0:
                return re.sub(r"\s+", " ", text[max(0, index - width // 2): index + width // 2]).strip()
        return re.sub(r"\s+", " ", text[:width]).strip()

    @staticmethod
    def _metric_context(
        text: str, *, target_year: str = "", aliases: Iterable[str] = (), width: int = 440,
    ) -> str:
        """选择信息量最高的发电量证据窗，而非机械取页面中的第一次出现。

        新闻页标题经常先写“完成发电量”，正文后段才说明“2023 年全年”。对每一
        个发电量位置取窗后，优先选择同时含目标年、年度范围和站名的片段。
        """
        positions: set[int] = set()
        for term in _GENERATION_TERMS:
            positions.update(match.start() for match in re.finditer(re.escape(term), text, re.I))
        ranked: list[tuple[int, str]] = []
        for index in positions:
            context = re.sub(r"\s+", " ", text[max(0, index - width): index + width]).strip()
            lowered = context.lower()
            score = 0
            score += 5 if target_year and target_year in context else 0
            score += 4 if any(term.lower() in lowered for term in _ANNUAL_SCOPE_TERMS) else 0
            score -= 5 if any(term.lower() in lowered for term in _PARTIAL_SCOPE_TERMS) else 0
            score += 3 if any(str(alias).lower() in lowered for alias in aliases) else 0
            ranked.append((score, context))
        return max(ranked, key=lambda item: item[0])[1] if ranked else ""

    @staticmethod
    def _scope(context: str) -> tuple[str, str | None]:
        lowered = context.lower()
        annual = next((term for term in _ANNUAL_SCOPE_TERMS if term.lower() in lowered), None)
        partial = next((term for term in _PARTIAL_SCOPE_TERMS if term.lower() in lowered), None)
        # 年度明示优先于“某月发布”的页面时间；若正文明确写上半年/季度，仍不能
        # 当成全年，即便页面还提到了年度报告。
        if partial and not annual:
            return "partial", partial
        if annual:
            return "annual", annual
        return "unknown", None

    @staticmethod
    def _scope_near_generation(
        text: str, *, target_year: str = "", aliases: Iterable[str] = (), width: int = 180,
    ) -> tuple[str, str | None]:
        """只用紧邻“发电量”字段的期间词判定口径。

        一篇一季度新闻可能在页面下方出现“年度枯水期”等背景描述。此前把整段
        预览中的任意“年度”都视为全年，会把这种文章错误放行。这里对每个指标
        出现位置单独取窄窗，按目标年和电站名选最相关的一处；同一窄窗中若明确
        有季度/月度范围，季度/月度始终优先。
        """
        candidates: list[tuple[int, str, str | None]] = []
        for term in _GENERATION_TERMS:
            for match in re.finditer(re.escape(term), text, re.I):
                window = text[max(0, match.start() - width): match.end() + width]
                lowered = window.lower()
                annual = next((item for item in _ANNUAL_SCOPE_TERMS if item.lower() in lowered), None)
                partial = next((item for item in _PARTIAL_SCOPE_TERMS if item.lower() in lowered), None)
                score = 0
                score += 5 if target_year and target_year in window else 0
                score += 4 if any(str(alias).lower() in lowered for alias in aliases) else 0
                if partial:
                    # 明确的季度/月度口径比同窗中宽泛的“年度”背景词优先。
                    candidates.append((score + 2, "partial", partial))
                elif annual:
                    candidates.append((score + 1, "annual", annual))
                else:
                    candidates.append((score, "unknown", None))
        if candidates:
            _, scope, evidence = max(candidates, key=lambda item: item[0])
            return scope, evidence
        return CandidateRelevanceVerifier._scope(text)

    @staticmethod
    def _focused_evidence(context: str, *, target_year: str) -> str:
        """从证据窗中提取一两句可供人工阅读的期间与数值依据。"""
        if target_year:
            annual_pattern = "|".join(re.escape(term) for term in _ANNUAL_SCOPE_TERMS)
            generation_pattern = "|".join(re.escape(term) for term in _GENERATION_TERMS)
            # 每个“目标年份”独立向后找“年度范围 → 发电量”，并取跨度最短的
            # 一段。这样页面标题、导航中的同年字样不会吞掉正文证据。
            snippets: list[str] = []
            for year_match in re.finditer(re.escape(target_year), context):
                tail = context[year_match.end(): year_match.end() + 900]
                annual_match = re.search(annual_pattern, tail, re.I)
                if not annual_match:
                    continue
                generation_match = re.search(generation_pattern, tail[annual_match.end():], re.I)
                if not generation_match:
                    continue
                metric_end = year_match.end() + annual_match.end() + generation_match.end()
                sentence_end = context.find("。", metric_end)
                end = sentence_end + 1 if sentence_end >= 0 else metric_end + 160
                snippets.append(context[year_match.start():end])
            if snippets:
                best = min(snippets, key=len)
                return re.sub(r"\s+", " ", best).strip()[:600]
        # 不能在 802.71 这类小数点处分句；英文句号只在后面有空白时作为边界。
        sentences = re.split(r"(?<=[。！？])\s*|(?<=[.!?])\s+(?=[A-Za-z])", context)
        ranked: list[tuple[int, str]] = []
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            lowered = sentence.lower()
            score = 0
            score += 4 if target_year and target_year in sentence else 0
            score += 4 if any(term.lower() in lowered for term in _ANNUAL_SCOPE_TERMS) else 0
            score += 3 if any(term.lower() in lowered for term in _GENERATION_TERMS) else 0
            if score:
                ranked.append((score, sentence))
        if ranked:
            best = max(ranked, key=lambda item: item[0])[1]
            return best[:600]
        return context[:600]

    def verify(self, candidate: dict, *, station: dict, target_period: str, metric: str = "generation") -> RelevanceResult:
        text = self._text(candidate)
        aliases = self._aliases(station)
        matched_alias = next((name for name in aliases if name.lower() in text), None)
        year = str(target_period or "").strip()
        metric_context = self._metric_context(text, target_year=year, aliases=aliases)
        has_year = bool(year and year in metric_context)
        has_generation = any(term in text for term in _GENERATION_TERMS)
        has_annual_report = any(term in text for term in _ANNUAL_REPORT_TERMS)
        period_scope, scope_evidence = self._scope_near_generation(text, target_year=year, aliases=aliases)
        excluded = next((term for term in _EXCLUSION_TERMS if term in text), None)

        if excluded and not (has_generation and has_annual_report):
            return RelevanceResult(False, 0.0, f"背景或非目标资料：命中“{excluded}”", self._excerpt(text, (excluded,)), period_scope)
        if not matched_alias:
            return RelevanceResult(False, 0.0, "未找到目标电站名称、当地名称或别名", self._excerpt(text, aliases), period_scope)
        if not has_year:
            return RelevanceResult(False, 0.0, f"发电量证据附近未找到目标年份 {year}", metric_context or self._excerpt(text, (matched_alias,)), period_scope)
        if metric == "generation" and not (has_generation or has_annual_report):
            return RelevanceResult(False, 0.0, "未发现年度发电量或年度报告语义", metric_context or self._excerpt(text, (matched_alias, year)), period_scope)
        if metric == "generation" and period_scope == "partial":
            return RelevanceResult(False, 0.0, f"仅发现非全年口径：命中“{scope_evidence}”", metric_context, period_scope)
        if metric == "generation" and period_scope != "annual":
            return RelevanceResult(
                False, 0.0, "年度口径不明确：未找到全年、年度或截至年末等范围证据",
                metric_context or self._excerpt(text, (matched_alias, year)), period_scope,
            )

        score = 0.55
        score += 0.20 if matched_alias else 0.0
        score += 0.15 if has_year else 0.0
        score += 0.10 if has_generation else 0.0
        reason = f"全年口径已确认：命中电站、目标年份和年度发电量（范围证据：“{scope_evidence}”）"
        evidence = self._focused_evidence(text, target_year=year) if metric_context else self._excerpt(
            text, (matched_alias, year, *_GENERATION_TERMS, *_ANNUAL_REPORT_TERMS),
        )
        return RelevanceResult(True, min(score, 1.0), reason, evidence, period_scope)
