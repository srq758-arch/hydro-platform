"""pywebview 桌面应用主窗口。

最小 V1 GUI（符合文档第 18.3 节）：
- 开始任务按钮
- 任务状态
- 当前阶段
- 进度信息
- 候选结果
- Validation issues
- 证据摘要
- 复核按钮
- TaskScheduler自动调度（P0-3新增）
"""

import webview
import json
import sqlite3
from pathlib import Path
from typing import Optional

from hydro_platform.app.api import Api
from hydro_platform.app.workers.simple_worker import SimpleWorker, WorkerEvent
from hydro_platform.app.scheduler.task_scheduler import TaskScheduler
from hydro_platform.config.paths import get_database_path
from hydro_platform.database.connection import connect
from hydro_platform.intelligence.web_search import SearchRuntime


def _pipeline_result_for_ui(result: dict) -> dict:
    """将可信 Pipeline 的结果转换为桌面端稳定的事件契约。

    ``run_collection_task`` 使用 ``failure_stage`` / ``error``，而早期
    前端事件使用 ``error_stage`` / ``error_message``。同时保留两组字段，
    以避免真实失败被降级显示为“未知错误”。
    """
    status = result["status"]
    failure_stage = result.get("failure_stage")
    error_message = result.get("error")
    failed = status == "failed"

    return {
        "status": status,
        "task_id": result["task_id"],
        "final_status": result["final_status"],
        "documents_archived": result["documents_archived"],
        "candidates_extracted": result["candidates_extracted"],
        "candidates_promoted": result["candidates_promoted"],
        "review_ids": result.get("review_ids", []),
        "promoted_keys": result.get("promoted_keys", []),
        "failure_stage": failure_stage,
        "error": error_message,
        "error_stage": failure_stage or ("UNKNOWN" if failed else None),
        "error_code": "PIPELINE_FAILED" if failed else None,
        "error_message": error_message or ("Pipeline 未返回失败原因" if failed else None),
    }


class HydroPlatformApp:
    """pywebview 桌面应用主类。"""

    def __init__(self):
        # 不在 __init__ 中创建 Api 实例，避免 pywebview 序列化时递归
        # 不存储 window 引用，避免循环引用导致序列化错误
        self.current_worker: Optional[SimpleWorker] = None
        self._window_ref = None  # 内部使用，不暴露给 pywebview
        self.scheduler: Optional[TaskScheduler] = None  # 任务调度器
        # 桌面进程级搜索运行时：前台来源发现与后台并发任务共用配额窗口。
        self._search_runtime = SearchRuntime()

    def _get_api(self, data_mode="production"):
        """惰性获取 API；默认生产，测试必须显式选择。"""
        mode = data_mode or "production"
        return Api(
            data_mode=mode,
            search_runtime=(self._search_runtime if mode == "production" else None),
        )

    # ========== 只读产品 API（暴露给前端）==========
    def get_dashboard(self):
        return self._get_api().get_dashboard()

    def list_stations(self, search=None, country=None, status=None,
                      min_capacity=None, max_capacity=None, limit=50, offset=0):
        return self._get_api().list_stations(search, country, status,
                                       min_capacity, max_capacity, limit, offset)

    def list_countries(self):
        return self._get_api().list_countries()

    def get_station_detail(self, entity_id):
        return self._get_api().get_station_detail(entity_id)

    def get_station_generation(self, entity_id):
        return self._get_api().get_station_generation(entity_id)

    def discover_trusted_sources(self, entity_id, target_period, limit=10, period_type="calendar_year"):
        """融合真实搜索、DeepSeek 搜索与 GEM 外链；不启动采集。"""
        return self._get_api().discover_trusted_sources(entity_id, target_period, limit, period_type)

    def discover_official_sources(self, entity_id, target_period=None, limit=10, period_type="calendar_year"):
        """旧前端缓存兼容别名，统一转入可信来源发现。"""
        return self._get_api().discover_trusted_sources(entity_id, target_period or "", limit, period_type)

    def list_data_gaps(self, limit=50, offset=0):
        return self._get_api().list_data_gaps(limit, offset)

    def detect_data_gaps(self, limit=100):
        return self._get_api().detect_data_gaps(limit)

    def get_data_coverage_stats(self):
        return self._get_api().get_data_coverage_stats()

    def browse_records(self, entity_id=None, year=None, value_type=None,
                       published_only=False, limit=100, offset=0):
        return self._get_api().browse_records(entity_id, year, value_type,
                                        published_only, limit, offset)

    def get_top100(self, year=None):
        return self._get_api().get_top100(year)

    # ========== 复核中心 API ==========
    def list_review_items(self, status=None, limit=50, offset=0):
        return self._get_api().list_review_items(status, limit, offset)

    def get_review_detail(self, record_id):
        return self._get_api().get_review_detail(record_id)

    def get_review_ocr_preview(self, review_id, page_number=None, dpi=150):
        return self._get_api().get_review_ocr_preview(review_id, page_number, dpi)

    def approve_record(self, record_id):
        return self._get_api().approve_record(record_id)

    def reject_record(self, record_id, reason):
        return self._get_api().reject_record(record_id, reason)

    def batch_approve(self, record_ids):
        """批量批准复核项，沿用 API 的逐条事务和结果结构。"""
        return self._get_api().batch_approve(record_ids)

    def batch_reject(self, record_ids, reason):
        """批量驳回复核项，沿用 API 的逐条事务和结果结构。"""
        return self._get_api().batch_reject(record_ids, reason)

    def global_search(self, query):
        """统一搜索入口，避免前端绕过 API 直接访问数据库。"""
        return self._get_api().global_search(query)

    def open_review_window(self, record_id):
        """打开独立复核窗口；未启动 GUI 时返回可诊断的失败结构。"""
        review_id = str(record_id)
        review_html = Path(__file__).resolve().parent / "review_window.html"
        if self._window_ref is None or not review_html.exists():
            return {"status": "failed", "review_id": review_id, "message": "复核窗口尚未初始化"}
        try:
            review_window = webview.create_window(
                "复核详情",
                url=f"{review_html.as_uri()}?record_id={review_id}",
                width=1100,
                height=800,
                resizable=True,
                js_api=self,
            )
            return {"status": "success", "review_id": review_id, "window": bool(review_window)}
        except Exception as exc:
            return {"status": "failed", "review_id": review_id, "message": str(exc)}

    # ========== 来源管理 API ==========
    def list_sources(self, limit=100, offset=0):
        return self._get_api().list_sources(limit, offset)

    # ========== 文档资料 API ==========
    def list_documents(self, source_id=None, content_kind=None, limit=50, offset=0):
        return self._get_api().list_documents(source_id, content_kind, limit, offset)

    # ========== 证据中心 API ==========
    def list_evidence(self, document_id=None, limit=50, offset=0):
        return self._get_api().list_evidence(document_id, limit, offset)

    # ========== 项目管理 API ==========
    def list_projects(self, search=None, country=None, status=None, limit=50, offset=0):
        return self._get_api().list_projects(search, country, status, limit, offset)

    # ========== 任务管理 API ==========
    def list_tasks(self, status=None, limit=50, offset=0):
        return self._get_api().list_tasks(status, limit, offset)

    def create_task(
        self,
        entity_id: str,
        target_period: str,
        task_type: str = "generation_annual",
        period_type: str = "calendar_year",
    ):
        """创建一个待处理的采集任务，并保留统计周期口径。"""
        return self._get_api().create_task(
            entity_id, target_period, task_type, period_type=period_type
        )

    def create_intelligent_task(self, prompt: str, auto_execute: bool = False):
        """由自然语言创建 DeepSeek 联网来源规划任务。"""
        return self._get_api().create_intelligent_task(prompt, auto_execute)

    def get_intelligent_task_plan(self, plan_id: str):
        return self._get_api().get_intelligent_task_plan(plan_id)

    def create_collection_task_from_intelligent_plan(self, plan_id: str, url: str):
        return self._get_api().create_collection_task_from_intelligent_plan(plan_id, url)

    def cancel_queued_task(self, task_id: str):
        return self._get_api().cancel_queued_task(task_id)

    def retry_failed_task(self, task_id: str):
        return self._get_api().retry_failed_task(task_id)

    def restart_intelligent_task(self, task_id: str):
        return self._get_api().restart_intelligent_task(task_id)

    def cancel_test_tasks(self):
        return self._get_api().cancel_test_tasks()

    # ========== 设置 API ==========
    def get_system_info(self):
        return self._get_api().get_system_info()

    def get_ocr_capabilities(self):
        return self._get_api().get_ocr_capabilities()

    def get_data_space_info(self, data_mode="production"):
        return self._get_api(data_mode).get_data_space_info()

    def migrate_data_space(self, data_mode="production"):
        """用户明确确认后执行 schema 迁移；不在启动阶段隐式写生产库。"""
        return self._get_api(data_mode).migrate_data_space()

    def get_dashboard_test(self):
        return self._get_api("test").get_dashboard()

    def reset_test_data(self):
        return self._get_api("test").reset_test_data()

    def export_database(self):
        """导出数据库。"""
        return self._get_api().export_database()

    def rebuild_index(self):
        """重建数据库索引。"""
        return self._get_api().rebuild_index()

    # ========== LLM 配置管理 API ==========
    def get_llm_config(self):
        """获取 LLM 配置状态。"""
        return self._get_api().get_llm_config()

    def save_llm_config(self, provider, api_key, model=None, name=None):
        """保存 LLM 配置。"""
        return self._get_api().save_llm_config(provider, api_key, model, name)

    def switch_llm_config(self, provider, name):
        """切换活动的 LLM 配置。"""
        return self._get_api().switch_llm_config(provider, name)

    def delete_llm_config(self, provider, name):
        """删除指定的 LLM 配置。"""
        return self._get_api().delete_llm_config(provider, name)

    def test_llm_connection(self):
        """测试 LLM 连接。"""
        return self._get_api().test_llm_connection()

    def quit_app(self):
        """退出应用。"""
        # 停止调度器
        if self.scheduler:
            self.scheduler.stop()

        if self._window_ref:
            self._window_ref.destroy()
        return {"status": "quitting"}

    # ========== 任务调度器 API（P0-3新增）==========
    def get_scheduler_status(self):
        """获取调度器状态"""
        if not self.scheduler:
            return {"enabled": False}

        status = self.scheduler.get_status()
        return {
            "enabled": True,
            "running": status["running"],
            "paused": status["paused"],
            "active_tasks": status["active_tasks"],
            "total_tasks": status["total_tasks"],
            "completed_tasks": status["completed_tasks"],
            "queued_tasks": status["queued_tasks"],
            "uptime_seconds": status["uptime_seconds"]
        }

    def pause_scheduler(self):
        """暂停调度器"""
        if self.scheduler:
            self.scheduler.pause()
            return {"status": "paused"}
        return {"status": "no_scheduler"}

    def resume_scheduler(self):
        """恢复调度器"""
        if self.scheduler:
            self.scheduler.resume()
            return {"status": "resumed"}
        return {"status": "no_scheduler"}

    def start_scheduler(self):
        """启动调度器（如果未启动）"""
        if self.scheduler and not self.scheduler.running:
            self.scheduler.start()
            return {"status": "started"}
        elif self.scheduler and self.scheduler.running:
            return {"status": "already_running"}
        return {"status": "no_scheduler"}

    def stop_scheduler(self):
        """停止调度器"""
        if self.scheduler:
            self.scheduler.stop()
            return {"status": "stopped"}
        return {"status": "no_scheduler"}

    # ========== 采集任务 API ==========
    def start_task(self, task_config: dict) -> dict:
        """桌面端唯一的采集入口。

        不再以“缺少业务字段”为理由回退到历史的直写流程。所有采集必须
        绑定电站和目标年份，随后由可信 Pipeline 完成采集、归档、校验、证据
        绑定和复核。
        """
        if not task_config.get("entity_id") or not task_config.get("target_period"):
            return {
                "status": "failed",
                "error_stage": "VALIDATION",
                "error_code": "MISSING_BUSINESS_CONTEXT",
                "error_message": "采集任务必须指定目标电站和目标年份；旧桌面流程已停用。",
            }
        return self._start_trusted_task(task_config)

    def _start_trusted_task(self, task_config: dict) -> dict:
        """启动可信 Pipeline 任务。

        Args:
            task_config: {
                "type": "download_url" | "upload_file",
                "entity_id": str (必需，P0-2 新增),
                "target_period": str (必需，P0-2 新增),
                "url": str (如果 type=download_url),
                "file_path": str (如果 type=upload_file),
                "source_title": str (来源标题；兼容 source_id),
                "metadata": dict,
                "data_mode": str
            }

        Returns:
            {"status": "started", "task_id": str}
        """
        data_mode = task_config.get("data_mode", "production")
        entity_id = task_config.get("entity_id")
        target_period = task_config.get("target_period")
        period_type = task_config.get("period_type", "calendar_year")

        # P0-2: 业务语义校验
        if not entity_id or not target_period:
            return {
                "status": "failed",
                "error_stage": "VALIDATION",
                "error_code": "MISSING_BUSINESS_CONTEXT",
                "error_message": "必须指定电站 ID 和目标年份"
            }
        if period_type not in {"calendar_year", "fiscal_year"}:
            return {
                "status": "failed",
                "error_stage": "VALIDATION",
                "error_code": "INVALID_PERIOD_TYPE",
                "error_message": "期间类型只能是自然年或财政年度",
            }

        task_id = f"task_{entity_id}_{target_period}_{id(task_config)}"

        def task_callback(event: WorkerEvent):
            """Worker 回调：将事件发送到前端。"""
            window = self._window_ref
            if window:
                window.evaluate_js(f"""
                    if (window.onTaskEvent) {{
                        window.onTaskEvent({json.dumps({
                            "type": event.event_type,
                            "task_id": event.task_id,
                            "message": event.message,
                            "data": event.data
                        })});
                    }}
                """)

        worker = SimpleWorker(task_id, task_callback)

        def execute_task():
            """后台执行的任务逻辑（调用可信 Pipeline）。"""
            try:
                task_type = task_config["type"]
                # 新前端使用 source_title；保留 source_id 作为旧桌面调用的兼容别名。
                source_title = (
                    task_config.get("source_title")
                    or task_config.get("source_id")
                    or "桌面应用上传"
                )
                metadata = task_config.get("metadata", {})

                # 报告开始
                worker.report_state_change("PIPELINE_START", {"stage": "pipeline_start"})
                worker.report_progress(f"开始为电站 {entity_id} 采集 {target_period} 年数据...")

                # 调用可信 Pipeline 统一入口
                from hydro_platform.common.enums import ContentKind

                if task_type == "download_url":
                    url = task_config["url"]
                    worker.report_progress(f"开始采集 URL：{url}")
                    result = self._get_api(data_mode).run_collection_task(
                        entity_id=entity_id,
                        target_period=target_period,
                        url=url,
                        local_file=None,
                        source_title=source_title,
                        publisher=metadata.get("publisher"),
                        period_type=period_type,
                        # 用户确认的来源可能是 HTML 网页、PDF 或数据表；由采集器
                        # 根据实际响应头与文件签名识别，不能一律强制为 PDF。
                        expected=ContentKind.ANY
                    )
                elif task_type == "upload_file":
                    file_path = task_config["file_path"]
                    worker.report_progress(f"开始采集本地文件：{file_path}")
                    result = self._get_api(data_mode).run_collection_task(
                        entity_id=entity_id,
                        target_period=target_period,
                        url=None,
                        local_file=file_path,
                        source_title=source_title,
                        publisher=metadata.get("publisher"),
                        period_type=period_type,
                        expected=ContentKind.ANY
                    )
                else:
                    raise ValueError(f"未知任务类型：{task_type}")

                if worker.is_cancelled():
                    return {"status": "cancelled"}

                if result["status"] == "success":
                    worker.report_state_change("PIPELINE_COMPLETE", {"stage": "complete"})
                    worker.report_progress(
                        f"✓ Pipeline 完成：归档 {result['documents_archived']} 个文档，"
                        f"抽取 {result['candidates_extracted']} 条候选，"
                        f"发布 {result['candidates_promoted']} 条记录"
                    )
                elif result["status"] == "needs_review":
                    worker.report_state_change("PIPELINE_COMPLETE", {"stage": "complete"})
                    worker.report_progress(
                        f"⚠ Pipeline 完成但需要复核：{len(result.get('review_ids', []))} 条待复核"
                    )
                else:
                    worker.report_state_change(
                        "PIPELINE_FAILED",
                        {"stage": "failed", "failure_stage": result.get("failure_stage")},
                    )
                    worker.report_progress(f"✗ Pipeline 失败：{result.get('error', '未知错误')}")

                return _pipeline_result_for_ui(result)

            except Exception as e:
                # 未预期的错误
                import traceback
                tb = traceback.format_exc()
                print(f"[Worker V2] 未预期的错误:\n{tb}", flush=True)

                return {
                    "status": "failed",
                    "error_stage": "UNKNOWN",
                    "error_code": "UNEXPECTED_ERROR",
                    "error_message": f"Pipeline 执行失败：{str(e)[:200]}",
                    "error_details": {"technical": str(e)[:200]},
                    "error_traceback": tb
                }

        worker.start(execute_task)
        self.current_worker = worker

        return {"status": "started", "task_id": task_id}

    def cancel_task(self) -> dict:
        """取消当前任务（从 GUI 调用）。"""
        if self.current_worker:
            self.current_worker.cancel()
            return {"status": "cancelling"}
        return {"status": "no_task"}

    def get_task_status(self) -> dict:
        """获取当前任务状态（从 GUI 调用）。"""
        if self.current_worker:
            return {
                "running": self.current_worker.is_running(),
                "task_id": self.current_worker.task_id
            }
        return {"running": False}


def create_window():
    """创建并启动 pywebview 窗口，加载 app/web/ 下的静态前端。"""
    try:
        app = HydroPlatformApp()
    except Exception as e:
        print(f"初始化应用失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 定位静态前端目录：app/gui/main_window.py -> 上一级 app/ -> web/
    web_dir = Path(__file__).resolve().parent.parent / "web"
    index_html = web_dir / "index.html"
    if not index_html.exists():
        print(f"找不到前端入口: {index_html}")
        return

    # 仅对全新/空的用户数据空间做首次建库。已有生产库只读探测，避免
    # 启动阶段未经数据治理批准就迁移正式数据库。
    try:
        production_db_path = get_database_path("production")
        bootstrap_required = _production_database_needs_bootstrap(production_db_path)
        if bootstrap_required:
            init_result = Api(data_mode="production").initialize()
            print(
                f"[Database] 首次生产数据空间已初始化: "
                f"schema_version={init_result.get('schema_version')}"
            )
        else:
            print(f"[Database] 已有生产数据库，启动阶段不执行迁移: {production_db_path}")
    except Exception as e:
        print(f"[Database] 启动前数据库检查失败，停止启动: {e}")
        import traceback
        traceback.print_exc()
        return

    # 初始化TaskScheduler（P0-3新增）
    try:
        db_path = get_database_path("production")

        def task_executor_wrapper(task_id):
            """调度器任务执行器：调用Pipeline处理任务"""
            try:
                print(f"[Scheduler] 开始执行任务: {task_id}")

                # 通过API执行任务
                runtime = app.scheduler.search_runtime if app.scheduler else app._search_runtime
                api = Api(data_mode="production", search_runtime=runtime)
                result = api.execute_scheduled_task(task_id)

                print(f"[Scheduler] 任务完成: {task_id}, 状态={result.get('status')}")
                return result

            except Exception as e:
                print(f"[Scheduler] 任务执行失败: {task_id}, 错误={e}")
                import traceback
                traceback.print_exc()
                return {"status": "failed", "error": str(e)}

        app.scheduler = TaskScheduler(
            db_path=str(db_path),
            task_executor=task_executor_wrapper,
            max_workers=2,        # 最多2个并发任务
            scan_interval=10,     # 每10秒扫描一次
            search_runtime=app._search_runtime,
        )

        # 自动启动调度器
        app.scheduler.start()
        print("[Scheduler] 任务调度器已启动")

    except Exception as e:
        print(f"[Scheduler] 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        # 调度器失败不影响主程序运行

    try:
        window = webview.create_window(
            '全球水电数据平台',
            url=str(index_html),
            js_api=app,
            width=1440,
            height=900,
            min_size=(1200, 760),
            resizable=True,
        )
        app._window_ref = window  # 内部引用，不通过公开属性暴露
        webview.start(debug=True)
    except Exception as e:
        print(f"窗口启动失败: {e}")
        import traceback
        traceback.print_exc()


def _production_database_needs_bootstrap(db_path: Path) -> bool:
    """只读判断生产数据库是否需要首次建库。

    不存在、零字节或没有任何 SQLite 表的文件属于新安装残留，可以安全建库；
    已有 schema 的数据库一律返回 False，避免启动隐式迁移正式数据。
    """
    if not db_path.exists() or db_path.stat().st_size == 0:
        return True

    try:
        # 统一走 connection.connect，覆盖 Windows 跨盘只读锁与 immutable
        # 稳定快照回退；不要在这里重新拼接易错的 file:F:/... URI。
        conn = connect(db_path, read_only=True)
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        raise RuntimeError(f"生产数据库不可读：{db_path}") from exc
    return row is None


_UNUSED_OLD_HTML = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>全球水电站数据平台 V1</title>
        <style>
            body {
                font-family: 'Microsoft YaHei', sans-serif;
                margin: 20px;
                background: #f5f5f5;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                border-bottom: 2px solid #007bff;
                padding-bottom: 10px;
            }
            .task-form {
                margin: 20px 0;
                padding: 15px;
                background: #f8f9fa;
                border-radius: 4px;
            }
            .form-group {
                margin-bottom: 15px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
            }
            input, select {
                width: 100%;
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
                box-sizing: border-box;
            }
            button {
                background: #007bff;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
            }
            button:hover {
                background: #0056b3;
            }
            button:disabled {
                background: #ccc;
                cursor: not-allowed;
            }
            .status-panel {
                margin-top: 20px;
                padding: 15px;
                border-left: 4px solid #007bff;
                background: #e7f3ff;
            }
            .stage-badge {
                display: inline-block;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
                margin-right: 10px;
            }
            .stage-acquisition { background: #ffc107; color: #000; }
            .stage-parse { background: #17a2b8; color: #fff; }
            .stage-extraction { background: #28a745; color: #fff; }
            .error-panel {
                margin-top: 20px;
                padding: 15px;
                border-left: 4px solid #dc3545;
                background: #f8d7da;
                color: #721c24;
            }
            .results-panel {
                margin-top: 20px;
                padding: 15px;
                border-left: 4px solid #28a745;
                background: #d4edda;
            }
            .candidate {
                padding: 10px;
                margin: 5px 0;
                background: white;
                border-radius: 4px;
                border: 1px solid #dee2e6;
            }
            .hidden {
                display: none;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>全球水电站数据平台 V1</h1>

            <div class="task-form">
                <div class="form-group">
                    <label>任务类型：</label>
                    <select id="taskType" onchange="toggleTaskType()">
                        <option value="download_url">下载 URL</option>
                        <option value="upload_file">上传本地文件</option>
                    </select>
                </div>

                <div class="form-group" id="urlGroup">
                    <label>文档 URL：</label>
                    <input type="text" id="taskUrl" placeholder="https://example.com/report.pdf">
                </div>

                <div class="form-group hidden" id="fileGroup">
                    <label>本地文件路径：</label>
                    <input type="text" id="taskFile" placeholder="C:\\path\\to\\file.pdf">
                </div>

                <div class="form-group">
                    <label>来源 ID：</label>
                    <input type="text" id="sourceId" placeholder="例如：三峡集团">
                </div>

                <button id="startBtn" onclick="startTask()">开始任务</button>
                <button id="cancelBtn" onclick="cancelTask()" disabled>取消</button>
            </div>

            <div id="statusPanel" class="status-panel hidden">
                <h3>任务状态</h3>
                <div id="statusContent"></div>
            </div>

            <div id="errorPanel" class="error-panel hidden">
                <h3>错误信息</h3>
                <div id="errorContent"></div>
            </div>

            <div id="resultsPanel" class="results-panel hidden">
                <h3>抽取结果</h3>
                <div id="resultsContent"></div>
            </div>
        </div>

        <script>
            function toggleTaskType() {
                const type = document.getElementById('taskType').value;
                if (type === 'download_url') {
                    document.getElementById('urlGroup').classList.remove('hidden');
                    document.getElementById('fileGroup').classList.add('hidden');
                } else {
                    document.getElementById('urlGroup').classList.add('hidden');
                    document.getElementById('fileGroup').classList.remove('hidden');
                }
            }

            function startTask() {
                const type = document.getElementById('taskType').value;
                const url = document.getElementById('taskUrl').value;
                const file = document.getElementById('taskFile').value;
                const sourceId = document.getElementById('sourceId').value;

                if (!sourceId) {
                    alert('请输入来源 ID');
                    return;
                }

                if (type === 'download_url' && !url) {
                    alert('请输入文档 URL');
                    return;
                }

                if (type === 'upload_file' && !file) {
                    alert('请输入文件路径');
                    return;
                }

                const config = {
                    type: type,
                    url: url,
                    file_path: file,
                    source_id: sourceId,
                    metadata: {}
                };

                pywebview.api.start_task(config).then(result => {
                    document.getElementById('startBtn').disabled = true;
                    document.getElementById('cancelBtn').disabled = false;
                    document.getElementById('statusPanel').classList.remove('hidden');
                    document.getElementById('errorPanel').classList.add('hidden');
                    document.getElementById('resultsPanel').classList.add('hidden');
                    document.getElementById('statusContent').innerHTML = '任务已启动...';
                });
            }

            function cancelTask() {
                pywebview.api.cancel_task().then(result => {
                    document.getElementById('statusContent').innerHTML += '<br>正在取消...';
                });
            }

            // 接收后台事件
            window.onTaskEvent = function(event) {
                const statusContent = document.getElementById('statusContent');

                if (event.type === 'progress') {
                    statusContent.innerHTML += '<br>' + event.message;
                } else if (event.type === 'state_change') {
                    const stage = event.data.stage.toUpperCase();
                    statusContent.innerHTML += '<br><span class="stage-badge stage-' +
                        event.data.stage.toLowerCase() + '">' + stage + '</span>' + event.message;
                } else if (event.type === 'complete') {
                    document.getElementById('startBtn').disabled = false;
                    document.getElementById('cancelBtn').disabled = true;

                    const result = event.data.result;
                    if (result.status === 'success') {
                        statusContent.innerHTML += '<br><strong>✓ 任务完成</strong>';
                        displayResults(result.candidates);
                    } else if (result.status === 'failed') {
                        displayError(result);
                    }
                } else if (event.type === 'error') {
                    document.getElementById('startBtn').disabled = false;
                    document.getElementById('cancelBtn').disabled = true;
                    displayError({
                        error_stage: 'UNKNOWN',
                        error_code: event.data.error_type,
                        error_message: event.message
                    });
                }
            };

            function displayError(result) {
                const errorPanel = document.getElementById('errorPanel');
                const errorContent = document.getElementById('errorContent');
                errorPanel.classList.remove('hidden');

                errorContent.innerHTML =
                    '<span class="stage-badge stage-' + result.error_stage.toLowerCase() + '">' +
                    result.error_stage + '</span>' +
                    '<strong>' + result.error_code + '</strong><br>' +
                    result.error_message;
            }

            function displayResults(candidates) {
                const resultsPanel = document.getElementById('resultsPanel');
                const resultsContent = document.getElementById('resultsContent');
                resultsPanel.classList.remove('hidden');

                let html = '<p>共 ' + candidates.length + ' 条候选记录：</p>';
                candidates.forEach((c, i) => {
                    html += '<div class="candidate">' +
                        '<strong>#' + (i+1) + '</strong> ' +
                        '发电量: <strong>' + (c.generation_gwh || 'N/A') + ' GWh</strong><br>' +
                        '原始值: ' + c.value_raw + ' ' + c.unit_raw + '<br>' +
                        '置信度: ' + c.confidence +
                        (c.warnings.length > 0 ? '<br>警告: ' + c.warnings.join(', ') : '') +
                        '</div>';
                });
                resultsContent.innerHTML = html;
            }
        </script>
    </body>
    </html>
    """


if __name__ == '__main__':
    create_window()
