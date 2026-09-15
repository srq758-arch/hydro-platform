"""PDF 解析（文档 11）——pypdf 可选依赖，延迟导入。

抽取每页文本并汇总。pypdf 未安装时返回 ok=False（不崩溃），供上层降级或转人工。
对文本层中仍保留列间空白的 PDF，额外生成保守的二维 Table；扫描/OCR 或版面
信息已经丢失的文档仍明确保留为“无表格”，不会猜测单元格。
"""

from __future__ import annotations

import importlib.util
import io
import re

from ..common.enums import ContentKind
from .content import ParsedContent
from .content import Table


_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?")
_TABLE_HINTS = (
    "year", "annual", "generation", "output", "gwh", "mwh", "station",
    "全年", "年度", "发电", "电站", "总量", "同比", "统计",
)
_STRONG_TABLE_HINTS = (
    "annual", "generation", "output", "gwh", "mwh", "twh", "station",
    "全年", "年度", "发电", "电站", "总量", "同比", "统计",
)
_FIRST_COLUMN_HEADER_LABELS = {
    "name", "station", "station name", "电站", "电站名称", "年份", "年度",
    "year", "period", "时期",
}
_SEMANTIC_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_SEMANTIC_UNIT_RE = re.compile(
    r"(?i)(?:GWh|MWh|kWh|TWh|GW|MW|kW|亿千瓦时|亿度|万千瓦时|万度|千瓦时|兆瓦时|度|兆瓦|千瓦)"
)
_SEMANTIC_PERIOD_PATTERNS = (
    ("quarter", re.compile(r"(?i)\bq[1-4]\b|quarter|季度|第\s*[一二三四1-4]\s*季度")),
    ("annual", re.compile(r"(?i)annual|year|全年|年度")),
    ("month", re.compile(r"(?i)month|monthly|月份|月度")),
    ("half_year", re.compile(r"(?i)half[- ]?year|半年|半年度")),
)


def _split_layout_columns(line: str) -> list[str]:
    """按布局提取列；只接受两个以上空格或制表符，避免拆散正文句子。"""
    return [part.strip() for part in re.split(r"\s{2,}|\t+", line.strip()) if part.strip()]


def _extract_layout_tables(page_text: str, page_number: int) -> list[Table]:
    """从 pypdf layout 文本中保守识别表格行。"""
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []

    def flush() -> None:
        nonlocal current
        if len(current) >= 2:
            blocks.append(current)
        current = []

    for raw_line in page_text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        columns = _split_layout_columns(line)
        lower = line.lower()
        looks_like_header = any(hint in lower for hint in _TABLE_HINTS)
        if len(columns) >= 2 and (_NUMBER_RE.search(line) or looks_like_header):
            current.append(columns)
        else:
            flush()
    flush()

    tables: list[Table] = []
    for block in blocks:
        if len(block) < 2:
            continue
        data_start = 1
        for row_index, row in enumerate(block[1:], start=1):
            first = str(row[0] if row else "").strip().lower()
            first_is_header = (
                not first
                or first in _FIRST_COLUMN_HEADER_LABELS
                or first.startswith(("year ", "annual ", "generation ", "年份 ", "年度 "))
            )
            numeric_cells = sum(1 for cell in row[1:] if _NUMBER_RE.search(cell))
            if not first_is_header and numeric_cells:
                data_start = row_index
                break
        header_rows = block[:data_start]
        rows = block[data_start:]
        width = max([len(row) for row in block])
        header = []
        for column in range(width):
            parts: list[str] = []
            for row in header_rows:
                value = row[column].strip() if column < len(row) else ""
                if value and value not in parts:
                    parts.append(value)
            header.append(" ".join(parts))
        numeric_rows = sum(
            1 for row in rows if any(_NUMBER_RE.search(cell) for cell in row)
        )
        header_text = " ".join(header).lower()
        has_explicit_year_column = any(
            re.fullmatch(r"(?:year|period|年份|年度|时期)", value.strip().lower())
            for value in header
        )
        has_table_semantics = (
            any(hint in header_text for hint in _STRONG_TABLE_HINTS)
            or has_explicit_year_column
        )
        if numeric_rows < 1 or not has_table_semantics:
            continue
        width = max([len(header), *(len(row) for row in rows)])
        if width < 2:
            continue
        normalised_header = header + [""] * (width - len(header))
        normalised_rows = [row + [""] * (width - len(row)) for row in rows]
        tables.append(Table(
            headers=normalised_header,
            rows=normalised_rows,
            caption=f"PDF 第 {page_number} 页布局表格",
        ))
    return tables


def _extract_layout_continuation_rows(page_text: str, expected_width: int) -> list[list[str]]:
    """保守提取没有重复表头的续页数据行。

    续页只接受「列数与上一页一致、首列是实体文字、其余列均为数值」的连续
    行；正文句子、单列数字和不完整行都不会被当作续表。返回最长连续块，降低
    页眉/脚注中偶然出现类似数字的误拼接风险。
    """
    if expected_width < 2:
        return []
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append(current)
        current = []

    for raw_line in page_text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        columns = _split_layout_columns(line)
        first = columns[0].strip().lower() if columns else ""
        numeric_cells = sum(1 for cell in columns[1:] if _NUMBER_RE.search(cell))
        valid = (
            len(columns) == expected_width
            and bool(first)
            and not _NUMBER_RE.fullmatch(first)
            # “三峡电站”等真实实体名可以包含 station/电站；这里只排除明确的
            # 表头标签，不能用全量语义提示词做子串过滤。
            and first not in {"name", "station", "station name", "电站", "电站名称"}
            and numeric_cells >= expected_width - 1
        )
        if valid:
            current.append(columns)
        else:
            flush()
    flush()
    return max(blocks, key=len, default=[])


def _normalise_table_header(value: str) -> str:
    """生成用于跨页匹配的表头签名，不改变展示给用户的原始表头。"""
    # 年份、期间和单位属于数据语义，不能为了“看起来像同一张表”而抹掉。
    # 例如 2024 全年与 2025 全年使用同样的列名时，若跨页合并，续页数值会被
    # 错绑到上一页年份。因此这里只消除排版符号，保留语义 token。
    value = str(value).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)


def _table_header_signature(table: Table) -> tuple[str, ...]:
    """返回稳定的表头签名；空列不参与比较。"""
    return tuple(
        signature
        for signature in (_normalise_table_header(value) for value in (table.headers or []))
        if signature
    )


def _table_semantic_signature(table: Table) -> dict[str, tuple[str, ...]]:
    """提取用于诊断跨页误绑的年份、单位和期间 token。"""
    text = " ".join(str(value or "") for value in (table.headers or []))
    years = tuple(sorted(set(_SEMANTIC_YEAR_RE.findall(text))))
    units = tuple(sorted(set(match.group(0).lower() for match in _SEMANTIC_UNIT_RE.finditer(text))))
    periods: set[str] = set()
    for period, pattern in _SEMANTIC_PERIOD_PATTERNS:
        if pattern.search(text):
            periods.add(period)
    return {
        "years": years,
        "units": units,
        "periods": tuple(sorted(periods)),
    }


def _table_header_mismatch_reasons(previous: Table, current: Table) -> list[str]:
    """说明相邻页表头为何不能合并；结果只用于诊断，不参与业务猜测。"""
    reasons: list[str] = []
    if previous.n_cols != current.n_cols:
        reasons.append("column_count_changed")
    previous_semantics = _table_semantic_signature(previous)
    current_semantics = _table_semantic_signature(current)
    if previous_semantics["years"] != current_semantics["years"]:
        reasons.append("year_changed")
    if previous_semantics["units"] != current_semantics["units"]:
        reasons.append("unit_changed")
    if previous_semantics["periods"] != current_semantics["periods"]:
        reasons.append("period_changed")
    if not reasons:
        reasons.append("header_changed")
    return reasons


def _continuation_semantic_conflicts(page_text: str, previous_table: Table) -> list[str]:
    """检查无重复表头续页是否出现与上一页冲突的语义线索。

    无表头续页本身不能证明年份/单位/期间仍相同；一旦页内出现明确的冲突线索，
    宁可不推断续表，也不把数值绑定到错误的表头。
    """
    previous_semantics = _table_semantic_signature(previous_table)
    conflicts: list[str] = []
    page_years = tuple(sorted(set(_SEMANTIC_YEAR_RE.findall(page_text))))
    if previous_semantics["years"] and any(year not in previous_semantics["years"] for year in page_years):
        conflicts.append("year_changed")
    page_units = tuple(sorted(set(match.group(0).lower() for match in _SEMANTIC_UNIT_RE.finditer(page_text))))
    if previous_semantics["units"] and any(unit not in previous_semantics["units"] for unit in page_units):
        conflicts.append("unit_changed")
    page_periods: set[str] = set()
    for period, pattern in _SEMANTIC_PERIOD_PATTERNS:
        if pattern.search(page_text):
            page_periods.add(period)
    if previous_semantics["periods"] and any(period not in previous_semantics["periods"] for period in page_periods):
        conflicts.append("period_changed")
    return conflicts


def _merge_layout_tables_across_pages(
    page_tables: list[tuple[int, Table]],
) -> list[tuple[int, int, Table]]:
    """合并相邻页上重复表头的续表。

    只合并页码连续且表头签名完全一致的表格，避免把报告中恰好使用相同列名的
    两张独立表格误拼接。返回 ``(起始页, 结束页, 表格)``，调用方可以据此生成
    可复核的跨页定位信息。
    """
    merged: list[tuple[int, int, Table]] = []
    for page_number, table in page_tables:
        if merged:
            start_page, end_page, previous = merged[-1]
            same_page_sequence = page_number == end_page + 1
            same_headers = _table_header_signature(previous) == _table_header_signature(table)
            if same_page_sequence and same_headers and previous.headers and table.headers:
                previous.rows.extend(table.rows)
                merged[-1] = (
                    start_page,
                    page_number,
                    Table(
                        headers=list(previous.headers),
                        rows=previous.rows,
                        caption=f"PDF 第 {start_page}-{page_number} 页布局表格",
                    ),
                )
                continue
        merged.append((page_number, page_number, table))
    return merged


def pdf_available() -> bool:
    """pypdf 是否已安装（不解析，仅探测）。"""
    return importlib.util.find_spec("pypdf") is not None


def parse_pdf(body: bytes) -> ParsedContent:
    """解析 PDF 文本层。缺 pypdf 则 ok=False。"""
    if not pdf_available():
        return ParsedContent.unavailable(
            ContentKind.PDF, "未安装 pypdf，无法解析 PDF（pip install .[parsing]）"
        )
    from pypdf import PdfReader  # 延迟导入
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(body))
        pages: list[str] = []
        layout_pages: list[str] = []
        page_extract_errors: list[str] = []
        for page in reader.pages:
            try:
                plain = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - 单页文字层损坏仍可转 OCR
                plain = ""
                page_extract_errors.append(str(exc))
            pages.append(plain)
            try:
                layout = page.extract_text(extraction_mode="layout") or plain
            except Exception:  # noqa: BLE001 - 无文字层/旧版 pypdf 走 OCR 标记
                # 兼容较旧 pypdf：纯文本仍可被正文规则抽取。
                layout = plain
            layout_pages.append(layout)
    except (PdfReadError, Exception) as exc:  # noqa: BLE001 - 损坏 PDF 不致命
        return ParsedContent.unavailable(ContentKind.PDF, f"PDF 解析失败：{exc}")

    text = "\n".join(pages).strip()
    all_page_tables: list[tuple[int, Table]] = []
    inferred_continuation_pages: list[int] = []
    continuation_rejections: list[dict[str, object]] = []
    for page_number, layout in enumerate(layout_pages, start=1):
        extracted_page_tables = _extract_layout_tables(layout, page_number)
        # 先保留页表对，跨页合并需要同时看到页码和表头签名。
        if extracted_page_tables:
            all_page_tables.extend((page_number, table) for table in extracted_page_tables)
            continue
        # 某些 PDF 续页不重复表头，只有数据行；仅基于上一页最后一张表的列宽
        # 推断，并在 meta 中留下页码，供复核/统计区分“推断续表”。
        if all_page_tables and all_page_tables[-1][0] == page_number - 1:
            previous_table = all_page_tables[-1][1]
            semantic_conflicts = _continuation_semantic_conflicts(layout, previous_table)
            if semantic_conflicts:
                continuation_rejections.append({
                    "page": page_number,
                    "previous_page": page_number - 1,
                    "reasons": semantic_conflicts,
                })
                continue
            continuation_rows = _extract_layout_continuation_rows(
                layout, len(previous_table.headers or [])
            )
            if continuation_rows:
                all_page_tables.append((
                    page_number,
                    Table(
                        headers=list(previous_table.headers or []),
                        rows=continuation_rows,
                        caption=f"PDF 第 {page_number} 页布局续表（无重复表头）",
                    ),
                ))
                inferred_continuation_pages.append(page_number)
    table_merge_breaks: list[dict[str, object]] = []
    for (previous_page, previous_table), (page_number, table) in zip(
        all_page_tables, all_page_tables[1:]
    ):
        if page_number != previous_page + 1:
            continue
        if _table_header_signature(previous_table) == _table_header_signature(table):
            continue
        table_merge_breaks.append({
            "previous_page": previous_page,
            "page": page_number,
            "reasons": _table_header_mismatch_reasons(previous_table, table),
        })
    merged_tables = _merge_layout_tables_across_pages(all_page_tables)
    tables = [table for _, _, table in merged_tables]
    table_pages = [start_page for start_page, _, _ in merged_tables]
    table_page_spans = [
        [start_page, end_page] for start_page, end_page, _ in merged_tables
    ]
    text_layer_pages = sum(1 for page_text in pages if page_text.strip())
    needs_ocr = bool(pages) and text_layer_pages == 0
    return ParsedContent(
        kind=ContentKind.PDF,
        ok=True,
        text=text,
        tables=tables,
        meta={
            "n_pages": len(pages),
            "text_layer_pages": text_layer_pages,
            "needs_ocr": needs_ocr,
            "ocr_status": "required" if needs_ocr else "not_required",
            "page_extract_errors": page_extract_errors,
            "table_pages": table_pages,
            "table_page_spans": table_page_spans,
            "inferred_continuation_pages": inferred_continuation_pages,
            "continuation_rejections": continuation_rejections,
            "table_merge_breaks": table_merge_breaks,
            "table_detection": (
                "pypdf_layout_whitespace_v2_continuation"
                if inferred_continuation_pages
                else "pypdf_layout_whitespace_v1" if tables else "none"
            ),
        },
    )
