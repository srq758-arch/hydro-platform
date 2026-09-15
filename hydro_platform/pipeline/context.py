"""管线上下文与可注入依赖（文档 §22 步骤 14）。

Orchestrator 只依赖这里声明的接口，全部可注入——测试注入离线 fake（脚本化
Transport / FakeProvider / 自动 approve 的 ReviewDecider），生产注入真实实现。
这样端到端闭环既可离线确定性测试，又不破坏「未复核不进 Top100」的铁律。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from ..acquisition.router import AcquisitionRouter
from ..common.enums import ContentKind
from ..extraction.llm.provider import LLMProvider
from ..models.task import Task


@dataclass
class SourceRef:
    """一个任务要采集的来源引用：URL + 期望内容类型 + 元数据。"""

    url: str
    expected: ContentKind = ContentKind.ANY
    title: str | None = None
    publisher: str | None = None
    language: str | None = None


class UrlResolver(Protocol):
    """把一个 Task 解析成待采集来源列表（文档 §8 Discovery 的最小替身）。

    生产实现走真实发现逻辑；测试/单站闭环用固定映射。返回空列表表示无来源。
    """

    def resolve(self, task: Task) -> list[SourceRef]:  # pragma: no cover - 协议
        ...


class ReviewDecider(Protocol):
    """人工复核决策源——把「等人」抽象成可注入接口。

    生产实现即真实 Review Queue（返回 None 表示尚未决策，管线就停在断点）；
    测试注入自动 approve/reject，把闭环一次跑完。
    """

    def decide(self, review_id: str, task: Task) -> str | None:  # pragma: no cover
        ...


@dataclass
class PipelineContext:
    """一次管线运行所需的全部依赖与策略。"""

    conn: sqlite3.Connection
    router: AcquisitionRouter
    url_resolver: UrlResolver
    # 生产自动发现协调器。受控/手动 url_resolver 仍保留优先级，避免测试或用户
    # 明确指定 URL 时意外触发网络发现。
    discovery_resolver: object | None = None
    llm_provider: LLMProvider | None = None
    review_decider: ReviewDecider | None = None
    raw_root: Path | None = None
    # 给定 entity_id 返回 (capacity_mw, is_top100)，用于校验与复核判定；缺省从 stations 查
    entity_lookup: Callable[[str], tuple] | None = None
    # 使用 LLM 抽取（默认关闭；本期规则为真实路径，LLM 用 FakeProvider 时才开）
    use_llm: bool = False
    reviewer: str = "auto"
    # 单个原子任务最多尝试的候选来源数；不影响搜索召回，只限制实际采集预算。
    max_source_attempts: int = 10
    # 扫描 PDF 的 OCR 可注入后端；缺省自动尝试 Pytesseract，失败则转人工复核。
    ocr_backend: object | None = None
    ocr_language: str = "eng"
    ocr_max_pages: int = 20
    # 可选的 1-based 页码→像素区域映射；用于已知表格/证据区域的定向 OCR。
    # 未提供时仍按整页 OCR，且候选必须进入人工复核。
    ocr_regions: dict[int, object] | None = None
    _notes: list[str] = field(default_factory=list)
