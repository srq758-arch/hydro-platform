"""已退役的旧候选写入器兼容边界。

历史实现会猜测业务语义并直接写正式表。V5.2 仅保留同名失败接口，让
陈旧的外部调用得到明确诊断；本模块不再包含任何数据库写入实现。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List


class RecordWriter:
    """退役接口；正式记录只能由统一 Promotion 服务产生。"""

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
        # V5.2-A 安全闸门：该旧写入器会猜测年份、actual 和 plant，并直接写入
        # generation_records。保留类名仅用于短期兼容和识别陈旧调用；任何调用
        # 都必须失败，正式写入只能通过 lifecycle.promote_candidate。
        raise RuntimeError(
            "RecordWriter 已禁用：禁止绕过 Validation/Evidence/Review/Promotion "
            "直接写入 generation_records"
        )
