"""Archive 归档单测：落盘、登记、幂等、不可覆盖、同 URL 变化建新版本。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydro_platform.common.enums import AccessMethod, ContentKind
from hydro_platform.acquisition.result import DownloadMeta, FetchResult
from hydro_platform.archive.archiver import ArchiveError, Archiver
from hydro_platform.database.repositories import DocumentRepository

PDF_BODY = b"%PDF-1.7\n" + b"data" * 100


def _meta(url="https://e.org/r.pdf", body=PDF_BODY, kind=ContentKind.PDF):
    import hashlib
    return DownloadMeta(
        original_url=url,
        final_url=url,
        status_code=200,
        content_type="application/pdf",
        file_size=len(body),
        content_hash=hashlib.sha256(body).hexdigest(),
        content_kind=kind,
        access_method=AccessMethod.HTTP,
        fetched_at="2026-01-01T00:00:00+00:00",
    )


def _result(url="https://e.org/r.pdf", body=PDF_BODY, kind=ContentKind.PDF):
    return FetchResult.ok(meta=_meta(url, body, kind), body=body)


def _archiver(db, tmp_path):
    return Archiver(db, raw_root=tmp_path / "raw")


def test_archive_writes_file_and_registers(db, tmp_path):
    arch = _archiver(db, tmp_path)
    res = arch.archive(_result(), entity_id="s1")
    assert res.newly_archived is True
    assert res.local_path.exists()
    assert res.local_path.read_bytes() == PDF_BODY
    assert "s1" in str(res.local_path)      # 按 entity 分目录
    assert res.local_path.suffix == ".pdf"  # 按类型定扩展名

    row = DocumentRepository(db).get(res.document.document_id)
    assert row is not None
    assert row["entity_id"] == "s1"
    assert row["version"] == 1
    assert row["content_hash"] == _meta().content_hash


def test_archive_is_idempotent(db, tmp_path):
    arch = _archiver(db, tmp_path)
    r1 = arch.archive(_result(), entity_id="s1")
    r2 = arch.archive(_result(), entity_id="s1")   # 同 URL 同内容
    assert r1.document.document_id == r2.document.document_id
    assert r2.newly_archived is False
    assert DocumentRepository(db).count() == 1


def test_same_url_new_content_makes_new_version(db, tmp_path):
    arch = _archiver(db, tmp_path)
    r1 = arch.archive(_result(body=PDF_BODY), entity_id="s1")
    r2 = arch.archive(_result(body=b"%PDF-1.7\nDIFFERENT" + b"x" * 200), entity_id="s1")
    # 内容变化 → 不同 document_id、版本递增、两份文件都在
    assert r1.document.document_id != r2.document.document_id
    assert r2.document.version == 2
    assert r1.local_path.exists() and r2.local_path.exists()
    repo = DocumentRepository(db)
    assert repo.count() == 2
    assert len(repo.versions_for_url("https://e.org/r.pdf")) == 2


def test_different_content_kind_extension(db, tmp_path):
    arch = _archiver(db, tmp_path)
    res = arch.archive(
        _result(url="https://e.org/data.json", body=b'{"gwh": 1}', kind=ContentKind.JSON),
    )
    assert res.local_path.suffix == ".json"


def test_unassigned_entity_goes_to_bucket(db, tmp_path):
    arch = _archiver(db, tmp_path)
    res = arch.archive(_result())   # 无 entity_id
    assert "_unassigned" in str(res.local_path)


def test_archive_rejects_failed_result(db, tmp_path):
    arch = _archiver(db, tmp_path)
    from hydro_platform.common.enums import AcquisitionErrorCode
    bad = FetchResult.fail(AcquisitionErrorCode.HTTP_404, "not found")
    with pytest.raises(ArchiveError):
        arch.archive(bad)
