"""写入层：将采集流程产生的候选记录存入数据库。

负责：
1. 将抽取的候选记录写入 generation_records（标记为 draft 状态）
2. 创建对应的证据记录（evidence 表）
3. 创建复核队列项（review_items 表，如果置信度低）
"""

from __future__ import annotations

import sqlite3
import hashlib
from datetime import datetime
from typing import Any, Dict, List
from pathlib import Path


def _utc_now() -> str:
    """返回当前 UTC 时间的 ISO8601 字符串。"""
    return datetime.utcnow().isoformat() + 'Z'


def _generate_evidence_id(document_id: str, snippet: str) -> str:
    """生成证据 ID（基于 document_id + snippet 的前 100 字符）。"""
    content = f"{document_id}:{snippet[:100]}"
    return f"ev_{hashlib.sha256(content.encode()).hexdigest()[:16]}"


class RecordWriter:
    """候选记录写入器。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save_candidates(
        self,
        candidates: List[Dict[str, Any]],
        document_id: str,
        source_id: str,
        entity_id: str | None = None,
        task_id: str | None = None,
    ) -> Dict[str, Any]:
        """保存抽取的候选记录到数据库。

        Args:
            candidates: 候选记录列表（来自 extract_file 的返回值）
            document_id: 文档 ID
            source_id: 来源 ID
            entity_id: 实体 ID（可选，桌面应用场景可能为空）
            task_id: 任务 ID（可选）

        Returns:
            {
                "saved": int,  # 成功保存的记录数
                "skipped": int,  # 跳过的记录数（无效或重复）
                "needs_review": int,  # 需要复核的记录数
                "record_ids": List[int]  # 插入的 generation_records.id
            }
        """
        saved = 0
        skipped = 0
        needs_review = 0
        record_ids = []

        for candidate in candidates:
            # 跳过无效候选（generation_gwh 为 None）
            if candidate.get("generation_gwh") is None:
                skipped += 1
                continue

            # 推断周期信息（从 snippet 或使用默认值）
            period_label = self._infer_period_label(candidate)
            period_type = "calendar_year"  # 默认为日历年

            # 创建证据记录
            evidence_id = _generate_evidence_id(document_id, candidate.get("snippet", ""))
            self._create_evidence(
                evidence_id=evidence_id,
                document_id=document_id,
                source_id=source_id,
                snippet=candidate.get("snippet", ""),
                confidence=1.0 if candidate.get("confidence") == "high" else 0.5,
                task_id=task_id,
            )

            # 创建发电量记录
            try:
                record_id = self._create_generation_record(
                    entity_id=entity_id or "unknown",
                    period_type=period_type,
                    period_label=period_label,
                    generation_gwh=candidate["generation_gwh"],
                    value_raw=candidate.get("value_raw", ""),
                    unit_raw=candidate.get("unit_raw", ""),
                    source_id=source_id,
                    evidence_id=evidence_id,
                    confidence=1.0 if candidate.get("confidence") == "high" else 0.5,
                    warnings=candidate.get("warnings", []),
                    task_id=task_id,
                )
                record_ids.append(record_id)
                saved += 1

                # 如果置信度低或有警告，创建复核队列项
                if candidate.get("confidence") == "low" or candidate.get("warnings"):
                    self._create_review_item(
                        entity_id=entity_id or "unknown",
                        period_label=period_label,
                        generation_gwh=candidate["generation_gwh"],
                        warnings=candidate.get("warnings", []),
                        evidence_id=evidence_id,
                        task_id=task_id,
                    )
                    needs_review += 1

            except sqlite3.IntegrityError:
                # 唯一约束冲突（重复记录），跳过
                skipped += 1
                continue

        self.conn.commit()

        return {
            "saved": saved,
            "skipped": skipped,
            "needs_review": needs_review,
            "record_ids": record_ids,
        }

    def _infer_period_label(self, candidate: Dict[str, Any]) -> str:
        """从候选记录推断周期标签（如 "2020"）。

        优先从 snippet 中提取年份，否则返回默认值。
        """
        import re
        snippet = candidate.get("snippet", "")
        # 简单正则：匹配 4 位年份（1900-2099）
        match = re.search(r'\b(19\d{2}|20\d{2})\b', snippet)
        if match:
            return match.group(1)
        # 默认返回当前年份
        return str(datetime.utcnow().year)

    def _create_evidence(
        self,
        evidence_id: str,
        document_id: str,
        source_id: str,
        snippet: str,
        confidence: float,
        task_id: str | None,
    ) -> None:
        """创建证据记录（幂等）。"""
        self.conn.execute(
            """
            INSERT OR IGNORE INTO evidence (
                evidence_id, document_id, source_id, fact_type, fact_key,
                snippet, confidence, created_at, task_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                document_id,
                source_id,
                "generation",
                f"{document_id}:{snippet[:50]}",
                snippet[:500],  # 限制长度
                confidence,
                _utc_now(),
                task_id,
            ),
        )

    def _create_generation_record(
        self,
        entity_id: str,
        period_type: str,
        period_label: str,
        generation_gwh: float,
        value_raw: str,
        unit_raw: str,
        source_id: str,
        evidence_id: str,
        confidence: float,
        warnings: List[str],
        task_id: str | None,
    ) -> int:
        """创建发电量记录，返回插入的 id。

        Raises:
            sqlite3.IntegrityError: 唯一约束冲突（重复记录）
        """
        cursor = self.conn.execute(
            """
            INSERT INTO generation_records (
                entity_id, period_type, period_label, generation_gwh,
                value_type, measurement_scope, value_raw, unit_raw,
                source_id, evidence_id, confidence, extractor,
                validation_status, review_status, publication_status,
                created_at, updated_at, task_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                period_type,
                period_label,
                generation_gwh,
                "actual",  # 默认为实际值
                "plant",  # 默认为单站
                value_raw,
                unit_raw,
                source_id,
                evidence_id,
                confidence,
                "rule_extractor_v1",
                "pending" if warnings else "passed",
                "open" if confidence < 0.8 else None,
                "draft",  # 初始状态为草稿
                _utc_now(),
                _utc_now(),
                task_id,
            ),
        )
        return cursor.lastrowid

    def _create_review_item(
        self,
        entity_id: str,
        period_label: str,
        generation_gwh: float,
        warnings: List[str],
        evidence_id: str,
        task_id: str | None,
    ) -> None:
        """创建复核队列项（幂等）。"""
        reason = "低置信度或存在警告：" + ", ".join(warnings) if warnings else "低置信度"
        fact_key = f"{period_label}:{generation_gwh}"

        self.conn.execute(
            """
            INSERT OR IGNORE INTO review_items (
                review_id, entity_id, fact_type, fact_key, reason,
                status, payload, created_at, task_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"rv_{hashlib.sha256(fact_key.encode()).hexdigest()[:16]}",
                entity_id,
                "generation",
                fact_key,
                reason,
                "open",
                evidence_id,  # 存储 evidence_id 方便后续查看
                _utc_now(),
                task_id,
            ),
        )
