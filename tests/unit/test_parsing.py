"""Parsing 层单测：HTML/JSON/CSV 解析、PDF 优雅降级、分发路由。无第三方依赖路径。"""

from __future__ import annotations

from hydro_platform.common.enums import ContentKind
from hydro_platform.extraction.rule_extractors import extract_candidates
from hydro_platform.parsing import (
    parse_bytes,
    parse_csv,
    parse_document,
    parse_html,
    parse_json,
    parse_pdf,
    pdf_available,
)
from hydro_platform.parsing.content import ParsedContent, Table
from hydro_platform.parsing.pdf_parser import (
    _extract_layout_continuation_rows,
    _extract_layout_tables,
    _merge_layout_tables_across_pages,
    _table_header_mismatch_reasons,
)

HTML = b"""<!DOCTYPE html><html><head><title>Annual Report 2024</title></head>
<body>
<h1>Hydropower Output</h1>
<p>Station generated 1234 GWh in 2024.</p>
<a href="https://e.org/data.csv">download</a>
<table>
  <tr><th>Year</th><th>GWh</th></tr>
  <tr><td>2023</td><td>1100</td></tr>
  <tr><td>2024</td><td>1234</td></tr>
</table>
</body></html>"""


def test_parse_html_text_title_links():
    pc = parse_html(HTML)
    assert pc.ok
    assert pc.title == "Annual Report 2024"
    assert "1234 GWh" in pc.text
    assert "https://e.org/data.csv" in pc.links
    # <script>/<style> 不该混进正文（此处无，但确认标题不重复进正文）
    assert "Annual Report 2024" not in pc.text


def test_parse_html_table():
    pc = parse_html(HTML)
    assert len(pc.tables) == 1
    t = pc.tables[0]
    assert t.headers == ["Year", "GWh"]
    assert t.rows == [["2023", "1100"], ["2024", "1234"]]
    assert t.n_cols == 2
    assert t.n_rows == 2


def test_parse_html_multilevel_table_headers_with_spans():
    html = """<table><caption>2024 年发电量</caption>
    <tr><th rowspan="2">电站名称</th><th colspan="2">2024 年第四季度</th><th colspan="2">2024 年全年</th></tr>
    <tr><th>总发电量（亿千瓦时）</th><th>同比变动（%）</th><th>总发电量（亿千瓦时）</th><th>同比变动（%）</th></tr>
    <tr><td>乌东德电站</td><td>84.71</td><td>3.79</td><td>396.47</td><td>13.56</td></tr>
    </table>"""
    table = parse_html(html).tables[0]
    assert table.caption == "2024 年发电量"
    assert table.headers == [
        "电站名称",
        "2024 年第四季度 总发电量（亿千瓦时）",
        "2024 年第四季度 同比变动（%）",
        "2024 年全年 总发电量（亿千瓦时）",
        "2024 年全年 同比变动（%）",
    ]
    assert table.rows == [["乌东德电站", "84.71", "3.79", "396.47", "13.56"]]


def test_parse_json_ok_and_bad():
    pc = parse_json(b'{"year": 2024, "gwh": 1234.5}')
    assert pc.ok
    assert pc.data["gwh"] == 1234.5

    bad = parse_json(b"{not json")
    assert not bad.ok
    assert bad.error


def test_parse_csv():
    pc = parse_csv(b"Year,GWh\n2023,1100\n2024,1234\n")
    assert pc.ok
    assert len(pc.tables) == 1
    t = pc.tables[0]
    assert t.headers == ["Year", "GWh"]
    assert t.rows == [["2023", "1100"], ["2024", "1234"]]


def test_parse_pdf_graceful_when_unavailable():
    # 本仓库未装 pypdf → 优雅降级 ok=False，不抛异常
    pc = parse_pdf(b"%PDF-1.7\nfake")
    if pdf_available():
        assert pc.kind == ContentKind.PDF
    else:
        assert not pc.ok
        assert "pypdf" in pc.error


def test_parse_pdf_extracts_layout_table_when_text_columns_survive():
    """真实生成一页文本型 PDF，验证表格而非仅正文被解析。"""
    if not pdf_available():
        return
    reportlab = __import__("importlib").util.find_spec("reportlab")
    if reportlab is None:
        return
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    stream = BytesIO()
    page = canvas.Canvas(stream, pagesize=letter)
    page.drawString(50, 760, "2024 Annual Generation")
    page.drawString(50, 720, "Station    2024 Annual Generation (GWh)    YoY (%)")
    page.drawString(50, 700, "Three Gorges Dam    829.11    3.29")
    page.save()

    parsed = parse_pdf(stream.getvalue())
    assert parsed.ok
    assert parsed.meta["table_detection"] == "pypdf_layout_whitespace_v1"
    assert parsed.meta["needs_ocr"] is False
    assert parsed.meta["table_pages"] == [1]
    assert parsed.tables[0].headers == [
        "Station", "2024 Annual Generation (GWh)", "YoY (%)"
    ]
    assert parsed.tables[0].rows == [["Three Gorges Dam", "829.11", "3.29"]]
    candidates = extract_candidates(
        parsed,
        entity_id="station-three-gorges",
        entity_names=("Three Gorges Dam",),
    )
    assert any(
        item.period_label == "2024"
        and item.generation_gwh == 829.11
        and item.locator == "page[1].table[0].row[0].col[1]"
        for item in candidates
    )


def test_pdf_layout_table_merges_multilevel_headers():
    tables = _extract_layout_tables(
        "Station    2024 Q4    2024 Annual\n"
        "Station    Generation (GWh)    YoY (%)\n"
        "Three Gorges Dam    143.72    829.11\n",
        3,
    )
    assert len(tables) == 1
    assert tables[0].headers == [
        "Station",
        "2024 Q4 Generation (GWh)",
        "2024 Annual YoY (%)",
    ]
    assert tables[0].rows == [["Three Gorges Dam", "143.72", "829.11"]]


def test_pdf_layout_table_keeps_station_name_containing_station_word():
    tables = _extract_layout_tables(
        "Station    2024 Annual Generation (GWh)    YoY (%)\n"
        "Three Gorges Dam hydroelectric station    829.11    3.29\n",
        4,
    )
    assert len(tables) == 1
    assert tables[0].rows == [["Three Gorges Dam hydroelectric station", "829.11", "3.29"]]


def test_pdf_layout_table_does_not_treat_spaced_narrative_as_table():
    """报告正文的段落空白不能仅凭年份/数字被误识别为表格。"""
    narrative = (
        "In July 2022, the Department published its Strategic Plan for Fiscal Years (FY) 2022    -\n"
        "2026, replacing the Strategic Plan for FY 2018-2022.    2\n"
    )
    assert _extract_layout_tables(narrative, 3) == []


def test_pdf_layout_tables_merge_consecutive_pages_and_keep_span_locator():
    headers = ["Station", "2024 Annual Generation (GWh)", "YoY (%)"]
    merged = _merge_layout_tables_across_pages([
        (1, Table(headers=headers, rows=[["Three Gorges Dam", "400.00", "1.0"]])),
        (2, Table(headers=headers, rows=[["Three Gorges Dam", "829.11", "3.29"]])),
    ])
    assert len(merged) == 1
    start, end, table = merged[0]
    assert (start, end) == (1, 2)
    assert table.rows == [
        ["Three Gorges Dam", "400.00", "1.0"],
        ["Three Gorges Dam", "829.11", "3.29"],
    ]
    parsed = ParsedContent(
        kind=ContentKind.PDF,
        text="",
        tables=[table],
        meta={"table_pages": [start], "table_page_spans": [[start, end]]},
    )
    candidates = extract_candidates(
        parsed,
        entity_id="station-three-gorges",
        entity_names=("Three Gorges Dam",),
    )
    assert any(
        item.generation_gwh == 829.11
        and item.locator == "page[1-2].table[0].row[1].col[1]"
        for item in candidates
    )


def test_pdf_layout_tables_do_not_merge_nonconsecutive_or_different_headers():
    first = Table(headers=["Station", "2024 Annual Generation (GWh)"], rows=[["A", "1"]])
    second = Table(headers=["Station", "2024 Annual Generation (GWh)"], rows=[["B", "2"]])
    different = Table(headers=["Station", "2024 Capacity (MW)"], rows=[["C", "3"]])
    changed_width = Table(
        headers=["Station", "2024 Annual Generation (GWh)", "YoY (%)"],
        rows=[["D", "4", "1.0"]],
    )
    assert len(_merge_layout_tables_across_pages([(1, first), (3, second)])) == 2
    assert len(_merge_layout_tables_across_pages([(1, first), (2, different)])) == 2
    assert _table_header_mismatch_reasons(first, different) == ["unit_changed", "period_changed"]
    assert _table_header_mismatch_reasons(first, changed_width) == ["column_count_changed"]


def test_pdf_layout_tables_do_not_merge_when_year_changes():
    """年份是表格语义，不能因列名相似而把 2025 数值绑定到 2024 表头。"""
    first = Table(headers=["Station", "2024 Annual Generation (GWh)"], rows=[["A", "1"]])
    second = Table(headers=["Station", "2025 Annual Generation (GWh)"], rows=[["B", "2"]])
    merged = _merge_layout_tables_across_pages([(1, first), (2, second)])
    assert len(merged) == 2
    assert _table_header_mismatch_reasons(first, second) == ["year_changed"]


def test_pdf_layout_continuation_rows_require_entity_and_numeric_columns():
    continuation = _extract_layout_continuation_rows(
        "Three Gorges Dam    829.11    3.29\n"
        "Baihetan hydroelectric plant    604.32    5.42\n"
        "三峡电站    829.11    3.29\n"
        "普通正文    2024 年报告发布\n"
        "只有一个数字 2024\n",
        expected_width=3,
    )
    assert continuation == [
        ["Three Gorges Dam", "829.11", "3.29"],
        ["Baihetan hydroelectric plant", "604.32", "5.42"],
        ["三峡电站", "829.11", "3.29"],
    ]


def test_pdf_layout_continuation_rows_reject_misaligned_columns():
    assert _extract_layout_continuation_rows(
        "Three Gorges Dam    829.11\n", expected_width=3
    ) == []


def test_parse_pdf_merges_repeated_header_across_pages():
    """真实两页文本 PDF：重复表头只保留一张表并记录页码范围。"""
    if not pdf_available():
        return
    reportlab = __import__("importlib").util.find_spec("reportlab")
    if reportlab is None:
        return
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    stream = BytesIO()
    page = canvas.Canvas(stream, pagesize=letter)
    header = "Station    2024 Annual Generation (GWh)    YoY (%)"
    page.drawString(50, 760, header)
    page.drawString(50, 740, "Three Gorges Dam    400.00    1.0")
    page.showPage()
    page.drawString(50, 760, header)
    page.drawString(50, 740, "Three Gorges Dam    829.11    3.29")
    page.save()

    parsed = parse_pdf(stream.getvalue())
    assert parsed.ok
    assert parsed.meta["table_pages"] == [1]
    assert parsed.meta["table_page_spans"] == [[1, 2]]
    assert len(parsed.tables) == 1
    assert parsed.tables[0].rows == [
        ["Three Gorges Dam", "400.00", "1.0"],
        ["Three Gorges Dam", "829.11", "3.29"],
    ]


def test_parse_pdf_merges_continuation_page_without_repeated_header():
    if not pdf_available():
        return
    reportlab = __import__("importlib").util.find_spec("reportlab")
    if reportlab is None:
        return
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    stream = BytesIO()
    page = canvas.Canvas(stream, pagesize=letter)
    header = "Station    2024 Annual Generation (GWh)    YoY (%)"
    page.drawString(50, 760, header)
    page.drawString(50, 740, "Three Gorges Dam    400.00    1.0")
    page.showPage()
    # 续页只保留数据行，不重复列头。
    page.drawString(50, 760, "Baihetan hydroelectric plant    604.32    5.42")
    page.save()

    parsed = parse_pdf(stream.getvalue())
    assert parsed.ok
    assert parsed.meta["table_detection"] == "pypdf_layout_whitespace_v2_continuation"
    assert parsed.meta["inferred_continuation_pages"] == [2]
    assert parsed.meta["table_page_spans"] == [[1, 2]]
    assert parsed.tables[0].rows == [
        ["Three Gorges Dam", "400.00", "1.0"],
        ["Baihetan hydroelectric plant", "604.32", "5.42"],
    ]


def test_parse_pdf_rejects_continuation_with_conflicting_year():
    """无重复表头续页出现新年份时，不把数值静默绑定到旧表头。"""
    if not pdf_available():
        return
    reportlab = __import__("importlib").util.find_spec("reportlab")
    if reportlab is None:
        return
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    stream = BytesIO()
    page = canvas.Canvas(stream, pagesize=letter)
    page.drawString(50, 760, "Station    2024 Annual Generation (GWh)    YoY (%)")
    page.drawString(50, 740, "Three Gorges Dam    400.00    1.0")
    page.showPage()
    # 看起来像续表，但页内明确出现 2025 语义线索，必须停止推断。
    page.drawString(50, 760, "2025 Annual Generation report")
    page.drawString(50, 740, "Baihetan hydroelectric plant    604.32    5.42")
    page.save()

    parsed = parse_pdf(stream.getvalue())
    assert parsed.ok
    assert parsed.tables[0].rows == [["Three Gorges Dam", "400.00", "1.0"]]
    assert parsed.meta["inferred_continuation_pages"] == []
    assert parsed.meta["continuation_rejections"] == [{
        "page": 2,
        "previous_page": 1,
        "reasons": ["year_changed"],
    }]


def test_parse_pdf_marks_image_only_document_for_ocr():
    """无文本层的 PDF 不静默当作“无数据”，而是明确要求 OCR/人工复核。"""
    if not pdf_available():
        return
    from io import BytesIO
    from pypdf import PdfWriter

    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(stream)

    parsed = parse_pdf(stream.getvalue())
    assert parsed.ok
    assert parsed.meta["text_layer_pages"] == 0
    assert parsed.meta["needs_ocr"] is True
    assert parsed.meta["ocr_status"] == "required"
    assert parsed.tables == []


def test_parse_bytes_dispatch_and_redetect():
    # kind=UNKNOWN 时按内容重探测
    pc = parse_bytes(HTML, ContentKind.UNKNOWN)
    assert pc.kind == ContentKind.HTML
    assert pc.ok

    pc2 = parse_bytes(b'{"a": 1}', ContentKind.JSON)
    assert pc2.ok and pc2.data == {"a": 1}


def test_parse_document_reads_archived_file(tmp_path):
    f = tmp_path / "doc.html"
    f.write_bytes(HTML)
    pc = parse_document(f, ContentKind.HTML)
    assert pc.ok
    assert pc.title == "Annual Report 2024"


def test_parse_document_missing_file(tmp_path):
    pc = parse_document(tmp_path / "nope.html", ContentKind.HTML)
    assert not pc.ok
    assert "读取归档文件失败" in pc.error
