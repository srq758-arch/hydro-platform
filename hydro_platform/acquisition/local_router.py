"""本地文件采集适配器（阶段 2：新增 LocalFileRouter）。

将本地文件包装为 FetchResult，与 URL 下载走同一归档/解析/抽取流程。
标记 AccessMethod.LOCAL_IMPORT，确保审计信息准确。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from ..common.enums import AccessMethod, AcquisitionErrorCode, ContentKind
from ..common.logging_setup import get_logger
from .result import DownloadMeta, FetchResult

logger = get_logger(__name__)


class LocalFileRouter:
    """本地文件采集适配器。"""

    def fetch(
        self,
        file_path: str | Path,
        *,
        expected: ContentKind = ContentKind.ANY,
    ) -> FetchResult:
        """读取本地文件并构造 FetchResult。

        Args:
            file_path: 本地文件路径
            expected: 期望的内容类型

        Returns:
            FetchResult（成功或失败）
        """
        path = Path(file_path)

        # 文件不存在
        if not path.exists():
            return FetchResult.fail(
                AcquisitionErrorCode.HTTP_404,
                f"本地文件不存在：{path}",
            )

        # 文件不可读
        if not path.is_file():
            return FetchResult.fail(
                AcquisitionErrorCode.ACQUISITION_FAILED,
                f"不是有效文件：{path}",
            )

        try:
            file_bytes = path.read_bytes()
        except PermissionError:
            return FetchResult.fail(
                AcquisitionErrorCode.HTTP_403,
                f"无权限读取文件：{path}",
            )
        except Exception as e:
            return FetchResult.fail(
                AcquisitionErrorCode.ACQUISITION_FAILED,
                f"读取文件失败：{e}",
            )

        # 空文件
        if not file_bytes:
            return FetchResult.fail(
                AcquisitionErrorCode.EMPTY_BODY,
                f"文件为空：{path}",
            )

        # 推断内容类型
        content_kind = self._guess_content_kind(path)
        content_type = self._content_type_from_kind(content_kind)

        # 检查期望类型
        if expected != ContentKind.ANY and content_kind != expected:
            return FetchResult.fail(
                AcquisitionErrorCode.NOT_EXPECTED_TYPE,
                f"期望 {expected.value}，实际为 {content_kind.value}",
            )

        # 计算哈希
        content_hash = hashlib.sha256(file_bytes).hexdigest()

        # 构造元数据
        meta = DownloadMeta(
            original_url=f"file://{path.absolute()}",
            final_url=f"file://{path.absolute()}",
            status_code=200,
            content_type=content_type,
            file_size=len(file_bytes),
            content_hash=content_hash,
            content_kind=content_kind,
            access_method=AccessMethod.LOCAL_IMPORT,  # 关键：标记为本地导入
            fetched_at=datetime.utcnow().isoformat() + 'Z',
        )

        logger.info("本地文件读取成功：%s (%d bytes, %s)", path, len(file_bytes), content_kind.value)
        return FetchResult.ok(meta=meta, body=file_bytes)

    def _guess_content_kind(self, path: Path) -> ContentKind:
        """根据文件扩展名推断 ContentKind。"""
        ext = path.suffix.lower()
        KIND_MAP = {
            ".pdf": ContentKind.PDF,
            ".xlsx": ContentKind.EXCEL,
            ".xls": ContentKind.EXCEL,
            ".csv": ContentKind.CSV,
            ".html": ContentKind.HTML,
            ".htm": ContentKind.HTML,
            ".json": ContentKind.JSON,
        }
        return KIND_MAP.get(ext, ContentKind.UNKNOWN)

    def _content_type_from_kind(self, kind: ContentKind) -> str:
        """从 ContentKind 推断 Content-Type。"""
        TYPE_MAP = {
            ContentKind.PDF: "application/pdf",
            ContentKind.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ContentKind.CSV: "text/csv",
            ContentKind.HTML: "text/html",
            ContentKind.JSON: "application/json",
        }
        return TYPE_MAP.get(kind, "application/octet-stream")
