"""HTML 解析（文档 11）。

抽取正文、标题、链接和 HTML 表格。表格会展开 ``rowspan``/``colspan`` 并合并多级
表头，避免把「2024 全年 → 总发电量（亿千瓦时）→ 396.47」拆成互不相关的文字。
解析本身不做业务判定；表格中的目标行和全年列由抽取器进一步判断。
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import TypeAlias

from ..common.enums import ContentKind
from .content import ParsedContent, Table

# 这些标签内的文本不计入正文
_SKIP_TEXT_TAGS = {"script", "style", "head", "title"}
_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
_RawCell: TypeAlias = tuple[str, int, int, bool]


def _positive_span(attrs: dict[str, str | None], name: str) -> int:
    """读取 HTML span 属性；坏值按 1 处理，解析不能因单元格属性失败。"""
    try:
        return max(1, int(attrs.get(name) or "1"))
    except ValueError:
        return 1


def _normalise_table(raw_rows: list[list[_RawCell]], caption: str | None) -> Table:
    """展开跨行/跨列单元格，并把连续的 th 行合并为列级复合表头。"""
    if not raw_rows:
        return Table(caption=caption)

    grid: dict[tuple[int, int], tuple[str, bool]] = {}
    max_row = max_col = -1
    for row_index, raw_row in enumerate(raw_rows):
        col_index = 0
        for text, rowspan, colspan, is_header in raw_row:
            while (row_index, col_index) in grid:
                col_index += 1
            for rr in range(row_index, row_index + rowspan):
                for cc in range(col_index, col_index + colspan):
                    grid[(rr, cc)] = (text, is_header)
                    max_row = max(max_row, rr)
                    max_col = max(max_col, cc)
            col_index += colspan

    logical_rows = [
        [grid.get((r, c), ("", False))[0] for c in range(max_col + 1)]
        for r in range(max_row + 1)
    ]
    header_row_count = 0
    for raw_row in raw_rows:
        if raw_row and all(cell[3] for cell in raw_row):
            header_row_count += 1
        else:
            break
    if not header_row_count:
        return Table(rows=logical_rows, caption=caption)

    headers: list[str] = []
    for col_index in range(max_col + 1):
        parts: list[str] = []
        for row_index in range(header_row_count):
            value = logical_rows[row_index][col_index].strip()
            if value and value not in parts:
                parts.append(value)
        headers.append(" ".join(parts))
    return Table(headers=headers, rows=logical_rows[header_row_count:], caption=caption)


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.links: list[str] = []
        self.text_parts: list[str] = []
        self.tables: list[Table] = []

        self._skip_depth = 0
        self._in_title = False
        # 表格状态。先保留物理单元格，表结束时再统一展开 rowspan/colspan。
        self._cur_table_rows: list[list[_RawCell]] | None = None
        self._cur_raw_row: list[_RawCell] | None = None
        self._cur_cell: list[str] | None = None
        self._cur_cell_span: tuple[int, int, bool] | None = None
        self._cur_caption: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = attr_map.get("href")
            if href:
                self.links.append(href)
        if tag == "table":
            self._cur_table_rows = []
            self._cur_caption = []
        elif tag == "caption" and self._cur_table_rows is not None:
            self._cur_caption = []
        elif tag == "tr" and self._cur_table_rows is not None:
            self._cur_raw_row = []
        elif tag in ("td", "th") and self._cur_raw_row is not None:
            self._cur_cell = []
            self._cur_cell_span = (
                _positive_span(attr_map, "rowspan"),
                _positive_span(attr_map, "colspan"),
                tag == "th",
            )

    def handle_endtag(self, tag):
        if tag in _SKIP_TEXT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("td", "th") and self._cur_cell is not None and self._cur_raw_row is not None:
            rowspan, colspan, is_header = self._cur_cell_span or (1, 1, tag == "th")
            self._cur_raw_row.append(("".join(self._cur_cell).strip(), rowspan, colspan, is_header))
            self._cur_cell = None
            self._cur_cell_span = None
        elif tag == "tr" and self._cur_raw_row is not None and self._cur_table_rows is not None:
            self._cur_table_rows.append(self._cur_raw_row)
            self._cur_raw_row = None
        elif tag == "table" and self._cur_table_rows is not None:
            caption = " ".join(self._cur_caption or []).strip() or None
            self.tables.append(_normalise_table(self._cur_table_rows, caption))
            self._cur_table_rows = None
            self._cur_caption = None
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data.strip()
            return
        if self._cur_cell is not None:
            self._cur_cell.append(data)
            return
        if self._cur_caption is not None and self._cur_table_rows is not None:
            self._cur_caption.append(data)
            return
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self.text_parts.append(stripped)


def parse_html(body: bytes | str, *, encoding: str = "utf-8") -> ParsedContent:
    """解析 HTML 字节/字符串为 ParsedContent。"""
    text = body.decode(encoding, errors="ignore") if isinstance(body, bytes) else body
    collector = _Collector()
    collector.feed(text)
    joined = " ".join(p for p in collector.text_parts if p != "\n")
    # 归一多余空白
    joined = " ".join(joined.split())
    return ParsedContent(
        kind=ContentKind.HTML,
        ok=True,
        text=joined,
        tables=collector.tables,
        links=collector.links,
        title=collector.title or None,
    )
