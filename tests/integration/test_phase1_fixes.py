#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 Phase 1 修复：TaskRunRepository 和异常处理

验证：
- TaskRunRepository 创建和查询功能
- PipelineError 异常包装
"""

import sys
import io
from pathlib import Path
import sqlite3

# ❌ 已删除全局stdout修改（步骤1.1修复）
# sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.database.repositories import TaskRunRepository
from hydro_platform.pipeline.error_handler import PipelineError, wrap_stage
from hydro_platform.common.enums import FailureStage


def test_task_run_repository():
    """测试 TaskRunRepository"""
    print("=" * 60)
    print("测试 TaskRunRepository")
    print("=" * 60)

    # 使用测试数据库
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    # 创建 task_runs 表
    conn.execute("""
        CREATE TABLE task_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            status TEXT NOT NULL,
            failure_stage TEXT,
            message TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT
        )
    """)

    repo = TaskRunRepository(conn)

    # 测试1：创建运行记录
    print("\n[测试1] 创建运行记录")
    run_id = repo.create_run(
        task_id="TASK-TEST-001",
        attempt=1,
        started_at="2026-09-07T10:00:00"
    )
    print(f"✅ 创建成功: run_id = {run_id}")

    # 测试2：标记成功
    print("\n[测试2] 标记运行成功")
    repo.update_run_success(
        run_id=run_id,
        finished_at="2026-09-07T10:05:00",
        message="Successfully processed 5 candidates"
    )
    print("✅ 标记成功")

    # 测试3：查询运行记录
    print("\n[测试3] 查询运行记录")
    runs = repo.get_runs_for_task("TASK-TEST-001")
    assert len(runs) == 1
    run = runs[0]
    print(f"✅ 查询成功:")
    print(f"   task_id: {run['task_id']}")
    print(f"   attempt: {run['attempt']}")
    print(f"   status: {run['status']}")
    print(f"   message: {run['message']}")
    print(f"   started_at: {run['started_at']}")
    print(f"   finished_at: {run['finished_at']}")

    # 测试4：创建失败记录
    print("\n[测试4] 创建失败运行记录")
    run_id2 = repo.create_run(
        task_id="TASK-TEST-002",
        attempt=1,
        started_at="2026-09-07T11:00:00"
    )
    repo.update_run_failure(
        run_id=run_id2,
        failure_stage=FailureStage.ACQUISITION_FAILED.value,
        message="HTTP 404 Not Found",
        finished_at="2026-09-07T11:01:00"
    )
    print("✅ 失败记录创建成功")

    # 测试5：查询最新运行
    latest = repo.get_latest_run("TASK-TEST-002")
    print(f"✅ 最新运行:")
    print(f"   status: {latest['status']}")
    print(f"   failure_stage: {latest['failure_stage']}")
    print(f"   message: {latest['message']}")

    # 测试6：统计
    print("\n[测试5] 统计")
    total = repo.count()
    success_count = repo.count_by_status("success")
    failed_count = repo.count_by_status("failed")
    print(f"✅ 总运行次数: {total}")
    print(f"   成功: {success_count}")
    print(f"   失败: {failed_count}")

    conn.close()
    print("\n✅ TaskRunRepository 测试通过\n")


def test_pipeline_error():
    """测试 PipelineError 异常包装"""
    print("=" * 60)
    print("测试 PipelineError 异常包装")
    print("=" * 60)

    # 测试1：基本异常包装
    print("\n[测试1] 基本异常包装")
    try:
        raise PipelineError(
            FailureStage.ACQUISITION_FAILED,
            "下载失败"
        )
    except PipelineError as e:
        assert e.stage == FailureStage.ACQUISITION_FAILED
        assert e.message == "下载失败"
        print(f"✅ 捕获异常: {e}")

    # 测试2：带原因的异常
    print("\n[测试2] 带原因的异常")
    try:
        original_error = ValueError("Invalid URL")
        raise PipelineError(
            FailureStage.ACQUISITION_FAILED,
            "采集失败",
            cause=original_error
        )
    except PipelineError as e:
        assert e.cause is not None
        assert isinstance(e.cause, ValueError)
        print(f"✅ 捕获异常: {e}")
        print(f"   原因: {e.cause}")

    # 测试3：装饰器包装
    print("\n[测试3] 装饰器包装")

    @wrap_stage(FailureStage.PARSE_FAILED)
    def parse_document_mock(content):
        if not content:
            raise ValueError("Empty content")
        return {"text": content}

    try:
        parse_document_mock("")
    except PipelineError as e:
        assert e.stage == FailureStage.PARSE_FAILED
        assert "parse_document_mock" in e.message.lower()
        print(f"✅ 装饰器捕获异常: {e.stage.value}")
        print(f"   消息: {e.message}")

    print("\n✅ PipelineError 测试通过\n")


def main():
    print("\n" + "=" * 60)
    print("Phase 1 基础功能测试")
    print("=" * 60 + "\n")

    try:
        # 测试 TaskRunRepository
        test_task_run_repository()

        # 测试 PipelineError
        test_pipeline_error()

        print("=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        print("\nPhase 1 基础设施已就绪：")
        print("- TaskRunRepository 可以记录任务执行审计")
        print("- PipelineError 可以统一包装异常")
        print("\n下一步：集成到 orchestrator.py")

        return 0

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
