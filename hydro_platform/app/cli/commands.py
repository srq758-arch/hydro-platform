"""CLI命令行入口

提供命令行界面执行任务、批量处理、复核等操作。

命令：
  hydro-v1 run-task       执行单个任务
  hydro-v1 batch-run      批量执行任务
  hydro-v1 review-list    列出待复核项
  hydro-v1 review-approve 批准记录
  hydro-v1 review-reject  拒绝记录
  hydro-v1 status         查看系统状态
"""

import sys
from pathlib import Path
import click
from typing import Optional

# 确保项目路径在 sys.path 中
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from hydro_platform.pipeline import orchestrator
from hydro_platform.pipeline.context import PipelineContext
from hydro_platform.database.connection import connect
from hydro_platform.database.repositories import TaskRepository, ReviewRepository
from hydro_platform.common.enums import TaskStatus
from hydro_platform.tasking.manager import TaskManager
from hydro_platform.config.paths import get_database_path


def get_db_path(db: Optional[str]) -> Path:
    """获取数据库路径（使用默认路径或用户指定路径）"""
    if db:
        return Path(db)
    return get_database_path("production")


def _row_value(row, key: str, default=None):
    """Read a repository row while keeping old pre-migration DBs usable."""
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        if key in row.keys():
            return row[key]
    except (AttributeError, TypeError):
        pass
    return default


def _task_from_row(task_row):
    """Rehydrate the complete Task context used by the unified pipeline.

    The CLI used to copy only the original scheduling fields, silently dropping
    period/source context that the web API preserved.  Keeping this mapping in a
    small tested helper prevents the compatibility entry point from changing the
    task semantics while still defaulting fields absent from legacy schemas.
    """
    from hydro_platform.models.task import Task
    from hydro_platform.common.enums import TaskStatus as TaskStatusEnum
    from hydro_platform.common.clock import now_iso

    return Task(
        task_id=_row_value(task_row, "task_id"),
        entity_id=_row_value(task_row, "entity_id"),
        entity_type=_row_value(task_row, "entity_type"),
        task_type=_row_value(task_row, "task_type"),
        target_period=_row_value(task_row, "target_period"),
        period_type=_row_value(task_row, "period_type", "calendar_year") or "calendar_year",
        status=TaskStatusEnum(_row_value(task_row, "status", "pending")),
        priority_tier=_row_value(task_row, "priority_tier"),
        collection_priority=_row_value(task_row, "collection_priority"),
        attempts=_row_value(task_row, "attempts", 0) or 0,
        max_attempts=_row_value(task_row, "max_attempts", 3) or 3,
        failure_stage=_row_value(task_row, "failure_stage"),
        last_error=_row_value(task_row, "last_error"),
        source_type=_row_value(task_row, "source_type", "automatic") or "automatic",
        user_specified_source=_row_value(task_row, "user_specified_source"),
        created_at=_row_value(task_row, "created_at") or now_iso(),
        updated_at=_row_value(task_row, "updated_at") or now_iso(),
    )


@click.group()
@click.version_option(version="1.0.0", prog_name="hydro-v1")
def cli():
    """全球水电数据平台 V1 命令行工具"""
    pass


@cli.command()
@click.option('--task-id', required=True, help='任务ID')
@click.option('--db', default=None, help='数据库路径（默认: 统一数据空间中的 hydro.db）')
@click.option('--verbose', is_flag=True, help='显示详细日志')
def run_task(task_id: str, db: Optional[str], verbose: bool):
    """执行单个任务

    示例：
      hydro-v1 run-task --task-id=task_tgd_2024
    """
    click.echo(f"[hydro-v1] 执行任务: {task_id}")

    db_path = get_db_path(db)

    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        conn = connect(db_path)
        task_repo = TaskRepository(conn)

        # 查询任务
        task_row = task_repo.get(task_id)
        if not task_row:
            click.echo(f"[错误] 任务不存在: {task_id}", err=True)
            conn.close()
            sys.exit(1)

        click.echo(f"任务信息:")
        click.echo(f"  实体: {task_row['entity_id']}")
        click.echo(f"  类型: {task_row['task_type']}")
        click.echo(f"  目标年份: {task_row['target_period']}")
        click.echo(f"  状态: {task_row['status']}")

        # 检查任务状态
        status = task_row['status']
        if status == TaskStatus.SUCCESS.value:
            click.echo("[提示] 任务已完成，跳过执行")
            conn.close()
            return
        elif status == TaskStatus.RUNNING.value:
            click.echo("[警告] 任务正在运行中")
            if not click.confirm("是否强制重新执行?"):
                conn.close()
                return

        # 将 Row 转换为 Task 对象；必须保留期间口径与来源上下文。
        task = _task_from_row(task_row)

        # 创建Pipeline上下文所需的依赖
        from hydro_platform.acquisition.router import AcquisitionRouter
        from hydro_platform.pipeline.source_resolver import resolve_sources_enhanced

        # 简化的UrlResolver（使用source_resolver）
        class SimpleUrlResolver:
            def resolve(self, task):
                # 返回空列表，让pipeline使用默认的discovery流程
                return []

        router = AcquisitionRouter()
        url_resolver = SimpleUrlResolver()

        ctx = PipelineContext(
            conn=conn,
            router=router,
            url_resolver=url_resolver
        )

        click.echo("\n开始执行Pipeline...")

        # 执行任务
        result = orchestrator.run_task(ctx, task)

        # 显示结果
        click.echo("\n" + "=" * 60)
        click.echo("执行结果:")
        click.echo("=" * 60)
        click.echo(f"任务ID: {result.task_id}")
        click.echo(f"最终状态: {result.final_status.value}")
        click.echo(f"到达阶段: {result.reached_stage}")
        click.echo(f"归档文档: {result.documents_archived}")
        click.echo(f"抽取候选: {result.candidates_extracted}")
        click.echo(f"发布记录: {result.candidates_promoted}")

        if result.review_ids:
            click.echo(f"\n待复核项: {len(result.review_ids)} 个")
            for review_id in result.review_ids[:5]:
                click.echo(f"  - {review_id}")

        if result.error:
            click.echo(f"\n错误: {result.error}", err=True)

        conn.close()

        # 返回码
        if result.succeeded:
            sys.exit(0)
        elif result.needs_review:
            sys.exit(0)  # 需要复核不算失败
        else:
            sys.exit(1)

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        import traceback
        if verbose:
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option('--seed-file', required=True, type=click.Path(exists=True), help='种子文件（CSV/JSON）')
@click.option('--db', default=None, help='数据库路径（默认: 统一数据空间中的 hydro.db）')
@click.option('--max-workers', default=2, help='最大并发数')
@click.option('--dry-run', is_flag=True, help='仅显示将要执行的任务，不实际执行')
def batch_run(seed_file: str, db: str, max_workers: int, dry_run: bool):
    """批量执行任务

    种子文件格式（CSV）：
      entity_id,canonical_name,country,target_year
      tgd,三峡水电站,CN,2024
      xld,溪洛渡水电站,CN,2024

    示例：
      hydro-v1 batch-run --seed-file=data/seeds/top100.csv
    """
    click.echo(f"[hydro-v1] 批量执行: {seed_file}")

    # 读取种子文件
    import csv
    import json

    seed_path = Path(seed_file)
    tasks = []

    if seed_path.suffix == '.csv':
        with open(seed_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tasks.append(row)
    elif seed_path.suffix == '.json':
        with open(seed_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            tasks = data if isinstance(data, list) else data.get('tasks', [])
    else:
        click.echo("[错误] 不支持的文件格式（仅支持CSV/JSON）", err=True)
        sys.exit(1)

    click.echo(f"加载了 {len(tasks)} 个任务")

    if dry_run:
        click.echo("\n[DRY RUN] 将要执行的任务:")
        for i, task in enumerate(tasks[:10], 1):
            click.echo(f"  {i}. {task.get('entity_id', 'N/A')} - {task.get('canonical_name', 'N/A')} ({task.get('target_year', 'N/A')})")
        if len(tasks) > 10:
            click.echo(f"  ... 还有 {len(tasks) - 10} 个任务")
        return

    # TODO: 实现批量执行逻辑（使用TaskScheduler或多线程）
    click.echo("\n[提示] 批量执行功能即将实现")
    click.echo(f"配置: max_workers={max_workers}")
    click.echo("建议使用TaskScheduler后台调度器自动执行")


@cli.command()
@click.option('--db', default=None, help='数据库路径（默认: 统一数据空间中的 hydro.db）')
@click.option('--status', type=click.Choice(['pending', 'approved', 'rejected', 'all']), default='pending', help='复核状态')
@click.option('--limit', default=20, help='显示数量')
def review_list(db: str, status: str, limit: int):
    """列出待复核项

    示例：
      hydro-v1 review-list
      hydro-v1 review-list --status=approved --limit=50
    """
    click.echo(f"[hydro-v1] 复核列表 (status={status}, limit={limit})")

    db_path = get_db_path(db)
    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        conn = connect(db_path)

        # 直接查询review_items表
        if status == 'pending':
            query = """
                SELECT
                    ri.review_id,
                    ri.entity_id,
                    ri.fact_key,
                    ri.reason,
                    ri.status,
                    ri.created_at
                FROM review_items ri
                WHERE ri.status = 'open'
                ORDER BY ri.created_at DESC
                LIMIT ?
            """
        elif status == 'all':
            query = """
                SELECT
                    ri.review_id,
                    ri.entity_id,
                    ri.fact_key,
                    ri.reason,
                    ri.status,
                    ri.created_at
                FROM review_items ri
                ORDER BY ri.created_at DESC
                LIMIT ?
            """
        else:
            # status可能是approved/rejected等
            query = """
                SELECT
                    ri.review_id,
                    ri.entity_id,
                    ri.fact_key,
                    ri.reason,
                    ri.status,
                    ri.created_at
                FROM review_items ri
                WHERE ri.status = ?
                ORDER BY ri.created_at DESC
                LIMIT ?
            """

        if status == 'all' or status == 'pending':
            reviews = conn.execute(query, (limit,)).fetchall()
        else:
            reviews = conn.execute(query, (status, limit)).fetchall()

        if not reviews:
            click.echo("[提示] 没有找到复核项")
            conn.close()
            return

        click.echo(f"\n找到 {len(reviews)} 个复核项:\n")
        click.echo(f"{'复核ID':<40} {'实体ID':<25} {'原因':<30} {'状态':<10}")
        click.echo("-" * 110)

        for review in reviews:
            review_id = review['review_id'][:38]
            entity_id = review.get('entity_id', 'N/A')[:23]
            reason = review.get('reason', 'N/A')[:28]
            stat = review.get('status', 'N/A')

            click.echo(f"{review_id:<40} {entity_id:<25} {reason:<30} {stat:<10}")

        conn.close()

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--record-id', required=True, help='记录ID')
@click.option('--db', default=None, help='数据库路径（默认: 统一数据空间中的 hydro.db）')
def review_approve(record_id: str, db: str):
    """批准记录

    示例：
      hydro-v1 review-approve --record-id=xxx
    """
    click.echo(f"[hydro-v1] 批准记录: {record_id}")

    db_path = get_db_path(db)
    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        conn = connect(db_path)
        review_repo = ReviewRepository(conn)

        # 批准
        result = review_repo.approve(record_id, reviewer="CLI用户")

        if result:
            click.echo("[成功] 记录已批准")
        else:
            click.echo("[失败] 批准失败", err=True)
            sys.exit(1)

        conn.close()

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--record-id', required=True, help='记录ID')
@click.option('--reason', required=True, help='拒绝理由')
@click.option('--db', default=None, help='数据库路径（默认: 统一数据空间中的 hydro.db）')
def review_reject(record_id: str, reason: str, db: str):
    """拒绝记录

    示例：
      hydro-v1 review-reject --record-id=xxx --reason="数据不准确"
    """
    click.echo(f"[hydro-v1] 拒绝记录: {record_id}")
    click.echo(f"理由: {reason}")

    db_path = get_db_path(db)
    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        conn = connect(db_path)
        review_repo = ReviewRepository(conn)

        # 拒绝
        result = review_repo.reject(record_id, reason=reason, reviewer="CLI用户")

        if result:
            click.echo("[成功] 记录已拒绝")
        else:
            click.echo("[失败] 拒绝失败", err=True)
            sys.exit(1)

        conn.close()

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--metric', default='generation', type=click.Choice(['generation', 'capacity']), help='指标类型')
@click.option('--year', multiple=True, type=int, help='目标年份（可多次指定）')
@click.option('--priority', default=None, type=click.Choice(['A', 'B', 'C']), help='优先级过滤')
@click.option('--limit', default=None, type=int, help='限制生成数量')
@click.option('--db', default=None, help='数据库路径')
def generate_batch_tasks(metric: str, year: tuple, priority: str, limit: int, db: str):
    """批量生成采集任务

    示例：
      hydro-v1 generate-batch-tasks --year 2023 --limit 10
      hydro-v1 generate-batch-tasks --year 2022 --year 2023 --priority A
      hydro-v1 generate-batch-tasks --metric capacity --limit 50
    """
    click.echo(f"[hydro-v1] 批量生成任务")
    click.echo(f"  指标类型: {metric}")
    click.echo(f"  目标年份: {list(year) if year else [2023]}")
    click.echo(f"  优先级: {priority or '全部'}")
    click.echo(f"  数量限制: {limit or '无限制'}")

    db_path = get_db_path(db)
    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        from hydro_platform.registry.loader import MasterRegistry

        conn = connect(db_path)
        registry = MasterRegistry(conn)

        # 转换年份参数
        target_years = list(year) if year else [2023]

        # 生成任务
        task_ids = registry.generate_batch_tasks(
            metric=metric,
            target_years=target_years,
            priority_tier=priority,
            limit=limit
        )

        click.echo(f"\n[成功] 已生成 {len(task_ids)} 个任务")

        # 显示前10个任务ID
        if task_ids and len(task_ids) <= 20:
            click.echo("\n任务ID列表:")
            for tid in task_ids:
                click.echo(f"  - {tid}")
        elif task_ids:
            click.echo(f"\n任务ID样例（前10个）:")
            for tid in task_ids[:10]:
                click.echo(f"  - {tid}")
            click.echo(f"  ... 还有 {len(task_ids) - 10} 个任务")

        conn.close()

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option('--db', default=None, help='数据库路径')
def registry_stats(db: str):
    """显示注册表统计信息

    示例：
      hydro-v1 registry-stats
    """
    click.echo("[hydro-v1] 注册表统计")

    db_path = get_db_path(db)
    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        from hydro_platform.registry.loader import MasterRegistry

        conn = connect(db_path)
        registry = MasterRegistry(conn)

        stats = registry.get_registry_stats()

        click.echo("\n" + "=" * 60)
        click.echo("注册表统计")
        click.echo("=" * 60)

        # 电站统计
        st = stats['stations']
        click.echo("\n电站注册表:")
        click.echo(f"  总数: {st['total']}")
        click.echo(f"  优先级 A (Top100): {st['tier_a']}")
        click.echo(f"  优先级 B (中等): {st['tier_b']}")
        click.echo(f"  优先级 C (低): {st['tier_c']}")
        click.echo(f"  总装机容量: {st['total_capacity_mw']:.1f} MW")

        # 项目统计
        pj = stats['projects']
        click.echo("\n项目注册表:")
        click.echo(f"  总数: {pj['total']}")

        # 任务统计
        tk = stats['tasks']
        click.echo("\n任务统计:")
        click.echo(f"  总数: {tk['total']}")
        click.echo(f"  待执行: {tk['pending']}")
        click.echo(f"  运行中: {tk['running']}")
        click.echo(f"  已完成: {tk['done']}")
        click.echo(f"  失败: {tk['failed']}")

        click.echo("\n数据库: " + str(db_path))
        click.echo("=" * 60)

        conn.close()

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--status', default=None, help='按状态过滤 (announced/approved/under_construction/newly_commissioned)')
@click.option('--country', default=None, help='按国家过滤')
@click.option('--limit', default=None, type=int, help='限制生成数量')
@click.option('--db', default=None, help='数据库路径')
def generate_project_tasks(status: str, country: str, limit: int, db: str):
    """批量生成项目采集任务

    示例：
      hydro-v1 generate-project-tasks --status under_construction --limit 10
      hydro-v1 generate-project-tasks --country CN
    """
    click.echo(f"[hydro-v1] 批量生成项目任务")
    click.echo(f"  状态过滤: {status or '全部'}")
    click.echo(f"  国家: {country or '全部'}")
    click.echo(f"  数量限制: {limit or '无限制'}")

    db_path = get_db_path(db)
    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        from hydro_platform.registry.project_registry import ProjectRegistry

        conn = connect(db_path)
        registry = ProjectRegistry(conn)

        # 生成任务
        task_ids = registry.generate_project_tasks(
            status_filter=status,
            limit=limit
        )

        click.echo(f"\n[成功] 已生成 {len(task_ids)} 个项目任务")

        # 显示任务ID
        if task_ids and len(task_ids) <= 20:
            click.echo("\n任务ID列表:")
            for tid in task_ids:
                click.echo(f"  - {tid}")
        elif task_ids:
            click.echo(f"\n任务ID样例（前10个）:")
            for tid in task_ids[:10]:
                click.echo(f"  - {tid}")
            click.echo(f"  ... 还有 {len(task_ids) - 10} 个任务")

        conn.close()

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option('--db', default=None, help='数据库路径')
def project_stats(db: str):
    """显示项目注册表统计信息

    示例：
      hydro-v1 project-stats
    """
    click.echo("[hydro-v1] 项目注册表统计")

    db_path = get_db_path(db)
    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        from hydro_platform.registry.project_registry import ProjectRegistry

        conn = connect(db_path)
        registry = ProjectRegistry(conn)

        stats = registry.get_registry_stats()

        click.echo("\n" + "=" * 60)
        click.echo("项目注册表统计")
        click.echo("=" * 60)

        # 项目统计
        pj = stats['projects']
        click.echo("\n项目总览:")
        click.echo(f"  总数: {pj['total']}")
        click.echo(f"  已宣布: {pj['announced']}")
        click.echo(f"  已批准: {pj['approved']}")
        click.echo(f"  在建: {pj['under_construction']}")
        click.echo(f"  新投产: {pj['newly_commissioned']}")
        click.echo(f"  已运营: {pj['operational']}")
        click.echo(f"  总规划容量: {pj['total_capacity_mw']:.1f} MW")

        # 按国家统计
        if stats['by_country']:
            click.echo("\n前10个国家:")
            for item in stats['by_country'][:10]:
                click.echo(f"  {item['country']}: {item['count']} 个项目, {item['capacity_mw']:.1f} MW")

        # 按年份统计
        if stats['by_year']:
            click.echo("\n投产年份分布（前10）:")
            for item in stats['by_year'][:10]:
                click.echo(f"  {item['commissioning_year']}: {item['count']} 个项目")

        click.echo("\n数据库: " + str(db_path))
        click.echo("=" * 60)

        conn.close()

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--project-id', required=True, help='项目ID')
@click.option('--status', required=True, help='新状态')
@click.option('--date', default=None, help='生效日期 (YYYY-MM-DD)')
@click.option('--notes', default=None, help='备注信息')
@click.option('--db', default=None, help='数据库路径')
def update_project_status(project_id: str, status: str, date: str, notes: str, db: str):
    """更新项目状态

    示例：
      hydro-v1 update-project-status --project-id=PRJ001 --status=under_construction --date=2024-01-15
    """
    click.echo(f"[hydro-v1] 更新项目状态")
    click.echo(f"  项目ID: {project_id}")
    click.echo(f"  新状态: {status}")

    db_path = get_db_path(db)
    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        from hydro_platform.registry.project_registry import ProjectRegistry

        conn = connect(db_path)
        registry = ProjectRegistry(conn)

        # 更新状态
        registry.update_project_status(
            project_id=project_id,
            new_status=status,
            effective_date=date,
            notes=notes
        )

        click.echo(f"\n[成功] 项目状态已更新")

        # 显示历史
        history = registry.get_status_history(project_id)
        if history:
            click.echo(f"\n状态历史（最近5条）:")
            for h in history[:5]:
                click.echo(f"  {h['recorded_at'][:10]} - {h['status']} ({h.get('effective_date', 'N/A')})")

        conn.close()

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--db', default=None, help='数据库路径（默认: 统一数据空间中的 hydro.db）')
def status(db: str):
    """显示系统状态

    示例：
      hydro-v1 status
    """
    click.echo("[hydro-v1] 系统状态")

    db_path = get_db_path(db)
    if not db_path.exists():
        click.echo(f"[错误] 数据库不存在: {db_path}", err=True)
        sys.exit(1)

    try:
        conn = connect(db_path)

        # 统计任务
        task_stats = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM tasks
            GROUP BY status
        """).fetchall()

        # 统计记录
        record_stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN publication_status = 'publishable' THEN 1 ELSE 0 END) as publishable
            FROM generation_records
        """).fetchone()

        # 统计复核项
        review_stats = conn.execute("""
            SELECT
                COUNT(*) as pending
            FROM review_items
            WHERE status = 'open'
        """).fetchone()

        click.echo("\n" + "=" * 60)
        click.echo("系统状态概览")
        click.echo("=" * 60)

        click.echo("\n任务统计:")
        for row in task_stats:
            click.echo(f"  {row['status']}: {row['count']}")

        click.echo("\n记录统计:")
        click.echo(f"  总记录数: {record_stats['total']}")
        click.echo(f"  可发布: {record_stats['publishable']}")

        click.echo("\n复核统计:")
        click.echo(f"  待复核: {review_stats['pending']}")

        click.echo("\n数据库: " + str(db_path))
        click.echo("=" * 60)

        conn.close()

    except Exception as e:
        click.echo(f"[异常] {e}", err=True)
        sys.exit(1)


def main():
    """CLI入口"""
    cli()


if __name__ == '__main__':
    main()
