"""原始资料归档器（文档 10）。

把一次成功的 FetchResult 落盘并登记为 Document。核心不变量：
- 不能跳过 Archive：Parse 只应读归档后的本地文件。
- 原始资料不可覆盖：document_id 由 (URL, content_hash) 派生，重复归档幂等。
- 同 URL 内容变化 → 新 content_hash → 新 document_id + version+1（保留历史版本）。

落盘布局：raw/<entity_id>/<document_id><ext>，entity 缺失时归入 _unassigned。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..common.clock import now_iso
from ..common.enums import ContentKind
from ..common.exceptions import HydroError
from ..common.logging_setup import get_logger
from ..config import paths
from ..database.connection import transaction
from ..database.repositories import DocumentRepository
from ..models.document import Document
from ..acquisition.result import FetchResult

logger = get_logger(__name__)

# 内容类型 → 落盘扩展名
_EXT = {
    ContentKind.PDF: ".pdf",
    ContentKind.EXCEL: ".xlsx",
    ContentKind.CSV: ".csv",
    ContentKind.JSON: ".json",
    ContentKind.HTML: ".html",
    ContentKind.UNKNOWN: ".bin",
    ContentKind.ANY: ".bin",
}


class ArchiveError(HydroError):
    """归档失败（落盘或登记错误）。"""


@dataclass
class ArchiveResult:
    """归档结果。newly_archived=False 表示该文档此前已归档（幂等命中）。"""

    document: Document
    local_path: Path
    newly_archived: bool


class Archiver:
    """把 FetchResult 归档到 raw/ 并登记 documents 表。"""

    def __init__(self, conn, *, raw_root: Path | None = None) -> None:
        self.conn = conn
        self.repo = DocumentRepository(conn)
        self.raw_root = raw_root or paths.raw_dir()

    def archive(
        self,
        result: FetchResult,
        *,
        entity_id: str | None = None,
        task_id: str | None = None,
        source_id: str | None = None,
    ) -> ArchiveResult:
        """归档一次成功获取的原始资料。

        result 必须 success 且带 meta/body，否则抛 ArchiveError（不归档失败件）。
        幂等：同 document_id 已存在则直接返回既有记录，不重写文件、不改版本。
        """
        if not result.success or result.meta is None or result.body is None:
            raise ArchiveError("只能归档成功且带 body/meta 的 FetchResult")

        meta = result.meta
        doc_id = Document.derive_id(meta.original_url, meta.content_hash)

        existing = self.repo.get(doc_id)
        if existing is not None:
            logger.info("文档已归档，幂等跳过：%s", doc_id)
            return ArchiveResult(
                document=self._row_to_document(existing),
                local_path=Path(existing["local_path"]),
                newly_archived=False,
            )

        # 同 URL 已有其它版本 → 新版本号
        version = self.repo.max_version_for_url(meta.original_url) + 1

        local_path = self._target_path(entity_id, doc_id, meta.content_kind)
        self._write_bytes(local_path, result.body)

        doc = Document(
            document_id=doc_id,
            original_url=meta.original_url,
            final_url=meta.final_url,
            content_hash=meta.content_hash,
            file_size=meta.file_size,
            local_path=str(local_path),
            content_type=meta.content_type,
            content_kind=meta.content_kind,
            access_method=meta.access_method,
            fetched_at=meta.fetched_at,
            published_at=meta.published_at,
            entity_id=entity_id,
            task_id=task_id,
            source_id=source_id,
            version=version,
            created_at=now_iso(),
        )
        with transaction(self.conn):
            inserted = self.repo.insert_if_absent(doc)
        if not inserted:  # pragma: no cover - 竞态兜底
            logger.warning("并发归档命中已存在：%s", doc_id)
            return ArchiveResult(document=doc, local_path=local_path, newly_archived=False)

        logger.info(
            "归档 %s v%d → %s（%s, %d bytes）",
            doc_id, version, local_path, meta.content_kind.value, meta.file_size,
        )
        return ArchiveResult(document=doc, local_path=local_path, newly_archived=True)

    def _target_path(self, entity_id: str | None, doc_id: str, kind: ContentKind) -> Path:
        sub = entity_id or "_unassigned"
        ext = _EXT.get(kind, ".bin")
        return self.raw_root / sub / f"{doc_id}{ext}"

    def _write_bytes(self, path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # 原始资料不可覆盖：同名文件已在但 DB 无记录，视为异常状态，不静默覆盖
            logger.info("原始文件已存在，跳过写入（不可覆盖）：%s", path)
            return
        try:
            path.write_bytes(body)
        except OSError as exc:
            raise ArchiveError(f"落盘失败 {path}：{exc}") from exc

    @staticmethod
    def _row_to_document(row) -> Document:
        return Document(
            document_id=row["document_id"],
            original_url=row["original_url"],
            final_url=row["final_url"],
            content_hash=row["content_hash"],
            file_size=row["file_size"],
            local_path=row["local_path"],
            content_type=row["content_type"],
            content_kind=row["content_kind"] or ContentKind.UNKNOWN,
            access_method=row["access_method"],
            fetched_at=row["fetched_at"],
            published_at=row["published_at"],
            entity_id=row["entity_id"],
            task_id=row["task_id"],
            source_id=row["source_id"],
            version=row["version"],
            created_at=row["created_at"],
        )
