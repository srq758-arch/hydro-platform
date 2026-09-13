"""Acquisition 产出的数据类型（文档 9.4 / 10.3）。

FetchResult：一次获取的完整结果，成功时携带原始字节与文档元数据，失败时携带
    错误分类码与人类可读原因。Archive 层据此落盘并登记 document 元数据。
DownloadMeta：一份原始资料的元数据（文档 10.3 字段），content_hash 与 final_url
    在这里定型，供归档与去重使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..common.enums import AccessMethod, AcquisitionErrorCode, ContentKind


@dataclass
class DownloadMeta:
    """原始资料元数据（文档 10.3）。

    字节内容单独放在 FetchResult.body，元数据可独立序列化进库/日志（不含正文）。
    """

    original_url: str
    final_url: str
    status_code: int | None
    content_type: str | None
    file_size: int
    content_hash: str
    content_kind: ContentKind
    access_method: AccessMethod
    fetched_at: str
    published_at: str | None = None
    elapsed_ms: int | None = None


@dataclass
class FetchResult:
    """一次获取结果。用 ok()/fail() 构造。

    success 为整体结论；body 仅在成功时有值；meta 在成功时必有，失败时可能为 None
    （如连接超时根本没拿到响应）。error_code 取自 AcquisitionErrorCode。
    """

    success: bool
    meta: DownloadMeta | None = None
    body: bytes | None = None
    error_code: AcquisitionErrorCode | None = None
    error: str | None = None
    attempts: int = 1

    def __bool__(self) -> bool:
        return self.success

    @classmethod
    def ok(cls, *, meta: DownloadMeta, body: bytes, attempts: int = 1) -> "FetchResult":
        return cls(success=True, meta=meta, body=body, attempts=attempts)

    @classmethod
    def fail(
        cls,
        error_code: AcquisitionErrorCode,
        error: str,
        *,
        meta: DownloadMeta | None = None,
        attempts: int = 1,
    ) -> "FetchResult":
        return cls(
            success=False,
            error_code=error_code,
            error=error,
            meta=meta,
            attempts=attempts,
        )
