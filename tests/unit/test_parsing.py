"""Parsing 层单测：HTML/JSON/CSV 解析、PDF 优雅降级、分发路由。无第三方依赖路径。"""

from __future__ import annotations

from hydro_platform.common.enums import ContentKind
from hydro_platform.parsing import (
    parse_bytes,
    parse_csv,
    parse_document,
    parse_html,
    parse_json,
    parse_pdf,
    pdf_available,
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
