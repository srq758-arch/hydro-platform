"""Archive 原始资料归档层（文档 10）。

固定顺序 Acquisition → Archive → Parse，不能跳过 Archive。归档职责：
把 FetchResult 的原始字节落盘到 raw/，并登记 document 元数据（文档 10.3）。
原始资料不可覆盖：同一 (URL, 内容哈希) 幂等；同 URL 内容变化则建新版本、新 id。
"""

from .archiver import ArchiveResult, Archiver

__all__ = ["ArchiveResult", "Archiver"]
