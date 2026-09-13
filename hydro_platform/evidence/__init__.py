"""Evidence 层（文档 14）。

把候选事实钉回原始资料位置并落库。证据与原始资料（document_id+content_hash）
不可脱钩；原始资料不可覆盖，网页更新产生新文档版本。
"""

from __future__ import annotations

from .store import EvidenceStore, build_evidence_for_candidate

__all__ = ["EvidenceStore", "build_evidence_for_candidate"]
