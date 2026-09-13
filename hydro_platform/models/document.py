"""原始资料文档模型（文档 10.3）。

Document 记录一份已归档原始资料的元数据（不含正文字节）。document_id 由
(original_url, content_hash) 派生：同一 URL 内容变化即得到新 id 与新版本，
从而实现「原始资料不可覆盖，变化则建新版本」（文档 10.3）。
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, field_validator

from ..common.enums import AccessMethod, ContentKind


class Document(BaseModel):
    """一份归档原始资料的元数据。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str
    original_url: str
    final_url: str | None = None
    content_hash: str
    file_size: int
    local_path: str
    content_type: str | None = None
    content_kind: ContentKind = ContentKind.UNKNOWN
    access_method: AccessMethod | None = None
    fetched_at: str | None = None
    published_at: str | None = None
    entity_id: str | None = None
    task_id: str | None = None
    source_id: str | None = None
    version: int = 1
    created_at: str | None = None

    @field_validator("original_url")
    @classmethod
    def _url_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Document.original_url 不能为空")
        return v

    @staticmethod
    def derive_id(original_url: str, content_hash: str) -> str:
        """由 URL + 内容哈希派生稳定 document_id（同 URL 同内容 → 同 id）。"""
        digest = hashlib.sha1(
            f"{original_url}::{content_hash}".encode("utf-8")
        ).hexdigest()
        return f"doc_{digest[:16]}"
