"""Excel/CSV 表格解析（文档 11）。

CSV：标准库 csv，无依赖。
Excel(xlsx)：优先用 openpyxl（可选依赖），未装则尝试 pandas（已在核心依赖），
    两者都不可用时返回 ok=False 优雅降级。
不判断业务含义，只吐二维表。
"""

from __future__ import annotations

import csv
import importlib.util
import io

from ..common.enums import ContentKind
from .content import ParsedContent, Table


def parse_csv(body: bytes | str, *, encoding: str = "utf-8") -> ParsedContent:
    """解析 CSV 为单张 Table。首行作表头。"""
    text = body.decode(encoding, errors="ignore") if isinstance(body, bytes) else body
    reader = csv.reader(io.StringIO(text))
    rows = [list(r) for r in reader if r]
    if not rows:
        return ParsedContent(kind=ContentKind.CSV, ok=True, tables=[Table()])
    table = Table(headers=rows[0], rows=rows[1:])
    flat = "\n".join(", ".join(r) for r in rows)
    return ParsedContent(kind=ContentKind.CSV, ok=True, tables=[table], text=flat)


def _openpyxl_available() -> bool:
    return importlib.util.find_spec("openpyxl") is not None


def parse_excel(body: bytes) -> ParsedContent:
    """解析 xlsx 的所有工作表为多张 Table。缺依赖则 ok=False。"""
    if _openpyxl_available():
        return _parse_excel_openpyxl(body)
    if importlib.util.find_spec("pandas") is not None:
        return _parse_excel_pandas(body)
    return ParsedContent.unavailable(
        ContentKind.EXCEL, "未安装 openpyxl/pandas，无法解析 xlsx（pip install .[parsing]）"
    )


def _parse_excel_openpyxl(body: bytes) -> ParsedContent:
    import openpyxl  # 延迟导入

    try:
        wb = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - 损坏文件不致命
        return ParsedContent.unavailable(ContentKind.EXCEL, f"xlsx 解析失败：{exc}")
    tables: list[Table] = []
    text_parts: list[str] = []
    for ws in wb.worksheets:
        rows = [
            ["" if c is None else str(c) for c in row]
            for row in ws.iter_rows(values_only=True)
        ]
        rows = [r for r in rows if any(cell.strip() for cell in r)]
        if not rows:
            continue
        table = Table(headers=rows[0], rows=rows[1:], caption=ws.title)
        tables.append(table)
        text_parts.append("\n".join(", ".join(r) for r in rows))
    wb.close()
    return ParsedContent(
        kind=ContentKind.EXCEL, ok=True, tables=tables, text="\n\n".join(text_parts)
    )


def _parse_excel_pandas(body: bytes) -> ParsedContent:
    import pandas as pd  # 延迟导入

    try:
        sheets = pd.read_excel(io.BytesIO(body), sheet_name=None, header=None)
    except Exception as exc:  # noqa: BLE001
        return ParsedContent.unavailable(ContentKind.EXCEL, f"xlsx 解析失败：{exc}")
    tables: list[Table] = []
    text_parts: list[str] = []
    for name, df in sheets.items():
        rows = [["" if pd.isna(c) else str(c) for c in row] for row in df.values.tolist()]
        rows = [r for r in rows if any(cell.strip() for cell in r)]
        if not rows:
            continue
        tables.append(Table(headers=rows[0], rows=rows[1:], caption=str(name)))
        text_parts.append("\n".join(", ".join(r) for r in rows))
    return ParsedContent(
        kind=ContentKind.EXCEL, ok=True, tables=tables, text="\n\n".join(text_parts)
    )
