"""Ground Truth Benchmark 运行器。

加载 Ground Truth 样本，执行完整 Pipeline，对比期望值与实际抽取值。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

from hydro_platform.database.connection import connect
from hydro_platform.pipeline.orchestrator import run_task
from hydro_platform.pipeline.context import PipelineContext
# ❌ 已删除：TaskBuilder类不存在（步骤1.1修复）
# from hydro_platform.tasking.builder import TaskBuilder
from hydro_platform.common.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class GroundTruthCase:
    """Ground Truth 测试用例"""
    case_id: str
    entity_id: str
    canonical_name: str
    country: str
    year: int
    period_type: str
    expected_generation_gwh: float
    expected_unit: str
    source_url: str
    evidence_reference: str
    notes: str
    source_type: str
    manually_verified: bool
    verified_by: str
    verified_date: str


@dataclass
class CaseResult:
    """单个用例的执行结果"""
    case_id: str
    case_name: str

    # 各阶段是否成功
    source_discovered: bool
    acquisition_success: bool
    parse_success: bool
    extraction_success: bool

    # 字段级匹配
    entity_match: bool
    year_match: bool
    unit_match: bool
    value_accuracy: float  # 0-1，值匹配准确度

    # 整体
    overall_pass: bool
    error_stage: Optional[str]
    error_message: Optional[str]

    # 实际抽取值
    actual_generation_gwh: Optional[float]
    actual_year: Optional[int]
    actual_unit: Optional[str]


class BenchmarkRunner:
    """Benchmark 运行器"""

    def __init__(self, ground_truth_path: Path, db_path: Path = None):
        self.cases = self._load_ground_truth(ground_truth_path)
        self.db_path = db_path
        logger.info(f"加载 {len(self.cases)} 个 Ground Truth 用例")

    def _load_ground_truth(self, path: Path) -> List[GroundTruthCase]:
        """加载 Ground Truth 数据"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        cases = []
        for item in data:
            case = GroundTruthCase(**item)
            cases.append(case)

        return cases

    def run_all(self, limit: int = None) -> List[CaseResult]:
        """运行所有用例"""
        results = []
        cases_to_run = self.cases[:limit] if limit else self.cases

        logger.info(f"开始运行 {len(cases_to_run)} 个 Benchmark 用例")

        for i, case in enumerate(cases_to_run, 1):
            logger.info(f"[{i}/{len(cases_to_run)}] 运行用例: {case.case_id} - {case.canonical_name}")
            result = self._run_single_case(case)
            results.append(result)

            status = "PASS" if result.overall_pass else "FAIL"
            logger.info(f"  结果: {status}")

        return results

    def _run_single_case(self, case: GroundTruthCase) -> CaseResult:
        """运行单个用例"""
        conn = connect(self.db_path)

        try:
            # 1. 确保电站存在于 stations 表
            self._ensure_station_exists(conn, case)

            # 2. 构造 Task
            task = self._build_task(case)

            # 2.5. 注册任务到数据库（新增）
            self._register_task(conn, task)

            # 3. 执行 Pipeline
            ctx = self._build_pipeline_context(conn, case)
            pipeline_result = run_task(ctx, task)

            # 4. 查询抽取结果
            extracted = self._query_extracted_value(conn, case.entity_id, case.year)

            # 5. 对比
            result = self._compare(case, extracted, pipeline_result)

            return result

        except Exception as e:
            logger.error(f"用例 {case.case_id} 执行异常: {e}", exc_info=True)
            return CaseResult(
                case_id=case.case_id,
                case_name=case.canonical_name,
                source_discovered=False,
                acquisition_success=False,
                parse_success=False,
                extraction_success=False,
                entity_match=False,
                year_match=False,
                unit_match=False,
                value_accuracy=0.0,
                overall_pass=False,
                error_stage="unknown",
                error_message=str(e),
                actual_generation_gwh=None,
                actual_year=None,
                actual_unit=None
            )

        finally:
            conn.close()

    def _ensure_station_exists(self, conn, case: GroundTruthCase):
        """确保电站在数据库中存在"""
        row = conn.execute(
            "SELECT entity_id FROM stations WHERE entity_id = ?",
            (case.entity_id,)
        ).fetchone()

        if row is None:
            # 插入电站
            conn.execute("""
                INSERT INTO stations (entity_id, entity_type, canonical_name, country)
                VALUES (?, 'station', ?, ?)
            """, (case.entity_id, case.canonical_name, case.country))
            conn.commit()
            logger.debug(f"插入电站: {case.entity_id}")

    def _build_task(self, case: GroundTruthCase):
        """构造任务"""
        from hydro_platform.models.task import Task
        from hydro_platform.common.enums import TaskType, TaskStatus

        return Task(
            task_id=f"benchmark_{case.case_id}",
            entity_id=case.entity_id,
            entity_type="station",
            task_type=TaskType.STATION_GENERATION,
            target_period=str(case.year),
            status=TaskStatus.PENDING
        )

    def _register_task(self, conn, task):
        """注册任务到数据库"""
        from hydro_platform.database.repositories import TaskRepository

        # 检查任务是否已存在
        existing = conn.execute(
            "SELECT task_id FROM tasks WHERE task_id = ?",
            (task.task_id,)
        ).fetchone()

        if existing is None:
            # 插入新任务（使用upsert_many）
            repo = TaskRepository(conn)
            repo.upsert_many([task])
            conn.commit()
            logger.debug(f"注册任务: {task.task_id}")

    def _build_pipeline_context(self, conn, case: GroundTruthCase) -> PipelineContext:
        """构造 Pipeline 上下文"""
        from hydro_platform.acquisition.router import AcquisitionRouter

        # 简化版：只提供 URL resolver（直接返回 Ground Truth 中的 URL）
        def url_resolver(task):
            from hydro_platform.acquisition.result import SourceReference
            return [SourceReference(
                url=case.source_url,
                title=f"{case.canonical_name} Generation Data",
                publisher=f"{case.country} Official",
                expected="html"
            )]

        return PipelineContext(
            conn=conn,
            router=AcquisitionRouter(),
            url_resolver=url_resolver,
            use_llm=True,
            llm_provider=None  # 可选：配置 LLM provider
        )

    def _query_extracted_value(self, conn, entity_id: str, year: int) -> Optional[dict]:
        """查询抽取的发电量值"""
        row = conn.execute("""
            SELECT
                entity_id,
                period_label,
                generation_gwh,
                unit_raw,
                value_type,
                publication_status
            FROM generation_records
            WHERE entity_id = ?
            AND period_label = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (entity_id, str(year))).fetchone()

        if row is None:
            return None

        return dict(row)

    def _compare(
        self,
        expected: GroundTruthCase,
        actual: Optional[dict],
        pipeline_result
    ) -> CaseResult:
        """对比期望值与实际值"""

        if actual is None:
            # 没有抽取到任何值
            return CaseResult(
                case_id=expected.case_id,
                case_name=expected.canonical_name,
                source_discovered=pipeline_result.documents_archived > 0,
                acquisition_success=pipeline_result.documents_archived > 0,
                parse_success=False,
                extraction_success=False,
                entity_match=False,
                year_match=False,
                unit_match=False,
                value_accuracy=0.0,
                overall_pass=False,
                error_stage=pipeline_result.failure_stage.value if pipeline_result.failure_stage else "extraction",
                error_message="未抽取到发电量值",
                actual_generation_gwh=None,
                actual_year=None,
                actual_unit=None
            )

        # 字段级对比
        entity_match = actual['entity_id'] == expected.entity_id
        year_match = str(actual['period_label']) == str(expected.year)
        unit_match = self._normalize_unit(actual.get('unit_raw', '')) == expected.expected_unit

        # 值准确度（允许 5% 误差）
        value_accuracy = self._calc_value_accuracy(
            expected.expected_generation_gwh,
            actual['generation_gwh']
        )

        # 整体判定
        overall_pass = (
            entity_match and
            year_match and
            unit_match and
            value_accuracy >= 0.95  # 95% 准确度
        )

        return CaseResult(
            case_id=expected.case_id,
            case_name=expected.canonical_name,
            source_discovered=True,
            acquisition_success=True,
            parse_success=True,
            extraction_success=True,
            entity_match=entity_match,
            year_match=year_match,
            unit_match=unit_match,
            value_accuracy=value_accuracy,
            overall_pass=overall_pass,
            error_stage=None,
            error_message=None,
            actual_generation_gwh=actual['generation_gwh'],
            actual_year=int(actual['period_label']),
            actual_unit=actual.get('unit_raw')
        )

    def _normalize_unit(self, unit: str) -> str:
        """标准化单位"""
        unit = unit.upper().strip()
        if unit in ['GWH', 'GW·H', 'GW H']:
            return 'GWh'
        elif unit in ['TWH', 'TW·H']:
            return 'TWh'
        return unit

    def _calc_value_accuracy(self, expected: float, actual: float) -> float:
        """计算值准确度（0-1）"""
        if expected == 0:
            return 1.0 if actual == 0 else 0.0

        error_rate = abs(expected - actual) / expected

        if error_rate <= 0.05:  # 5% 误差内
            return 1.0
        elif error_rate <= 0.10:  # 10% 误差内
            return 0.9
        elif error_rate <= 0.20:  # 20% 误差内
            return 0.7
        else:
            return max(0.0, 1.0 - error_rate)
