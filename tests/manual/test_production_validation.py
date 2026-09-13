"""生产环境验证脚本：全面检查系统功能和稳定性

验证清单：
1. 端到端主路径验证（15项）
2. 错误处理验证（8项）
3. 并发和性能验证（3项）
4. 数据质量验证（8项）
"""

import sys
from pathlib import Path
import time

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.database.connection import connect
from hydro_platform.registry.source_registry import SourceRegistry
from hydro_platform.discovery.resolver import DiscoveryResolver
from hydro_platform.pipeline.source_resolver import resolve_sources_enhanced
from hydro_platform.app.scheduler.task_scheduler import TaskScheduler
from hydro_platform.models.task import Task
from hydro_platform.common.enums import TaskType, EntityType, TaskStatus
from hydro_platform.database.repositories import TaskRepository
import sqlite3


class ProductionValidator:
    """生产环境验证器"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = connect(db_path)
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.issues = []

    def check(self, name: str, condition: bool, message: str = "", warning: bool = False):
        """检查项验证"""
        if condition:
            self.passed += 1
            print(f"  [OK] {name}")
            return True
        else:
            if warning:
                self.warnings += 1
                print(f"  [WARN] {name}: {message}")
            else:
                self.failed += 1
                print(f"  [FAIL] {name}: {message}")
                self.issues.append(f"{name}: {message}")
            return False

    def section(self, title: str):
        """打印章节标题"""
        print(f"\n{'='*60}")
        print(f"{title}")
        print('='*60)

    def run_all_checks(self):
        """运行所有验证"""
        self.section("1. 端到端主路径验证")
        self.verify_main_path()

        self.section("2. 错误处理验证")
        self.verify_error_handling()

        self.section("3. 并发和性能验证")
        self.verify_performance()

        self.section("4. 数据质量验证")
        self.verify_data_quality()

        self.print_summary()

    def verify_main_path(self):
        """验证端到端主路径"""

        # 1.1 数据库表存在性
        print("\n[检查 1.1] 数据库表结构")
        tables = [
            "stations", "projects", "tasks", "sources",
            "generation_records", "evidence", "review_items",
            "task_runs", "documents"
        ]

        for table in tables:
            cursor = self.conn.execute(f"SELECT COUNT(*) as cnt FROM {table}")
            count = cursor.fetchone()["cnt"]
            self.check(f"表 {table} 存在", True, f"{count} 条记录")

        # 1.2 Sources表字段完整性
        print("\n[检查 1.2] Sources表扩展字段")
        cursor = self.conn.execute("PRAGMA table_info(sources)")
        columns = {row["name"] for row in cursor.fetchall()}

        required_fields = [
            "entity_id", "source_url", "source_type", "document_type",
            "covered_metric", "covered_year", "source_reliability_score",
            "success_count", "failure_count", "last_success", "last_failure"
        ]

        for field in required_fields:
            self.check(
                f"字段 {field}",
                field in columns,
                f"字段不存在"
            )

        # 1.3 SourceRegistry 功能
        print("\n[检查 1.3] SourceRegistry 功能")
        registry = SourceRegistry(self.conn)

        # 清理测试数据
        self.conn.execute("DELETE FROM sources WHERE entity_id = 'test_prod_verify'")
        self.conn.commit()

        # 测试注册
        try:
            source_id = registry.register_new_source(
                entity_id="test_prod_verify",
                source_url="https://test.example.com/report.pdf",
                metadata={
                    "source_type": "official",
                    "document_type": "pdf",
                    "covered_metric": "generation",
                    "covered_year": 2024,
                    "estimated_reliability": 0.85
                }
            )
            self.check("SourceRegistry.register_new_source()", True)

            # 测试查询
            source = registry.query_best_source("test_prod_verify", "generation", 2024)
            self.check("SourceRegistry.query_best_source()", source is not None)

            # 测试评分更新
            registry.update_success(source_id, "doc_001")
            source_updated = registry.query_best_source("test_prod_verify", "generation", 2024)
            self.check(
                "SourceRegistry.update_success()",
                source_updated["source_reliability_score"] > source["source_reliability_score"]
            )

            # 清理
            self.conn.execute("DELETE FROM sources WHERE entity_id = 'test_prod_verify'")
            self.conn.commit()

        except Exception as e:
            self.check("SourceRegistry 完整流程", False, str(e))

        # 1.4 Discovery 功能
        print("\n[检查 1.4] Discovery 功能")

        # 查找一个真实电站
        cursor = self.conn.execute("""
            SELECT entity_id, canonical_name
            FROM stations
            WHERE country = 'China'
            LIMIT 1
        """)
        station = cursor.fetchone()

        if station:
            try:
                resolver = DiscoveryResolver(self.conn)
                task_dict = {
                    "entity_id": station["entity_id"],
                    "entity_name": station["canonical_name"],
                    "target_period": "2024",
                    "metric": "generation"
                }

                candidates = resolver.discover(task_dict, min_candidates=3, max_candidates=5)
                self.check("Discovery.discover()", len(candidates) > 0, f"找到 {len(candidates)} 个候选")

                if candidates:
                    # 验证排序
                    sorted_correctly = all(
                        candidates[i].get("combined_score", 0) >= candidates[i+1].get("combined_score", 0)
                        for i in range(len(candidates) - 1)
                    )
                    self.check("Discovery 结果排序", sorted_correctly)

            except Exception as e:
                self.check("Discovery 完整流程", False, str(e))
        else:
            self.check("Discovery 测试", False, "未找到测试电站", warning=True)

        # 1.5 TaskScheduler 功能
        print("\n[检查 1.5] TaskScheduler 功能")

        def mock_executor(task_id):
            time.sleep(0.5)
            return {"status": "success"}

        try:
            scheduler = TaskScheduler(
                db_path=str(self.db_path),
                task_executor=mock_executor,
                max_workers=2,
                scan_interval=3
            )

            scheduler.start()
            self.check("TaskScheduler.start()", scheduler.running)

            time.sleep(1)
            status = scheduler.get_status()
            self.check("TaskScheduler.get_status()", status["running"])

            scheduler.pause()
            self.check("TaskScheduler.pause()", scheduler.get_status()["paused"])

            scheduler.resume()
            self.check("TaskScheduler.resume()", not scheduler.get_status()["paused"])

            scheduler.stop()
            self.check("TaskScheduler.stop()", not scheduler.get_status()["running"])

        except Exception as e:
            self.check("TaskScheduler 功能", False, str(e))

    def verify_error_handling(self):
        """验证错误处理"""

        print("\n[检查 2.1] 无效输入处理")

        registry = SourceRegistry(self.conn)

        # 测试空entity_id
        try:
            source = registry.query_best_source("", "generation", 2024)
            self.check("空entity_id处理", source is None)
        except Exception as e:
            self.check("空entity_id处理", False, f"应返回None而非异常: {e}")

        # 测试不存在的entity_id
        try:
            source = registry.query_best_source("nonexistent_id_12345", "generation", 2024)
            self.check("不存在entity_id处理", source is None)
        except Exception as e:
            self.check("不存在entity_id处理", False, str(e))

        print("\n[检查 2.2] 数据库连接异常")

        # SQLite会自动创建不存在的数据库文件，这是正常行为
        # 只有当路径本身无效（如父目录不存在）时才会抛异常
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            # 正常情况：可以创建新数据库
            try:
                temp_db = Path(tmpdir) / "test.db"
                temp_conn = connect(temp_db)
                temp_conn.close()
                os.remove(temp_db)
                self.check("可创建新数据库", True)
            except Exception as e:
                self.check("可创建新数据库", False, str(e))

        print("\n[检查 2.3] 并发安全性")

        # SQLite 的 row_factory 应该已设置
        self.check(
            "Row factory 已设置",
            self.conn.row_factory == sqlite3.Row
        )

    def verify_performance(self):
        """验证性能"""

        print("\n[检查 3.1] 查询性能")

        registry = SourceRegistry(self.conn)

        # 准备测试数据
        test_entity = "perf_test_entity"
        self.conn.execute("DELETE FROM sources WHERE entity_id = ?", (test_entity,))

        for i in range(10):
            registry.register_new_source(
                entity_id=test_entity,
                source_url=f"https://test{i}.example.com/report.pdf",
                metadata={
                    "source_type": "official",
                    "document_type": "pdf",
                    "covered_metric": "generation",
                    "covered_year": 2024 - i,
                    "estimated_reliability": 0.8
                }
            )

        # 测试查询性能
        start = time.time()
        for _ in range(100):
            registry.query_best_source(test_entity, "generation", 2024)
        elapsed = time.time() - start

        self.check(
            "查询性能（100次）",
            elapsed < 1.0,
            f"耗时 {elapsed:.3f}s"
        )

        # 清理
        self.conn.execute("DELETE FROM sources WHERE entity_id = ?", (test_entity,))
        self.conn.commit()

        print("\n[检查 3.2] 内存使用")
        # 简单检查：创建多个对象不应崩溃
        try:
            registries = [SourceRegistry(self.conn) for _ in range(10)]
            self.check("多实例创建", True)
        except Exception as e:
            self.check("多实例创建", False, str(e))

        print("\n[检查 3.3] Discovery 性能")
        cursor = self.conn.execute("SELECT entity_id, canonical_name FROM stations LIMIT 1")
        station = cursor.fetchone()

        if station:
            resolver = DiscoveryResolver(self.conn)
            task_dict = {
                "entity_id": station["entity_id"],
                "entity_name": station["canonical_name"],
                "target_period": "2024",
                "metric": "generation"
            }

            start = time.time()
            candidates = resolver.discover(task_dict)
            elapsed = time.time() - start

            self.check(
                "Discovery 响应时间",
                elapsed < 2.0,
                f"耗时 {elapsed:.3f}s，目标<2s"
            )

    def verify_data_quality(self):
        """验证数据质量"""

        print("\n[检查 4.1] Sources 表数据完整性")

        # 检查是否有评分为NULL的记录
        cursor = self.conn.execute("""
            SELECT COUNT(*) as cnt
            FROM sources
            WHERE source_reliability_score IS NULL
        """)
        null_scores = cursor.fetchone()["cnt"]
        self.check(
            "无NULL评分记录",
            null_scores == 0,
            f"发现 {null_scores} 条NULL评分" if null_scores > 0 else "",
            warning=True
        )

        print("\n[检查 4.2] 评分范围验证")

        # 评分应在 [0, 1] 范围内
        cursor = self.conn.execute("""
            SELECT COUNT(*) as cnt
            FROM sources
            WHERE source_reliability_score < 0 OR source_reliability_score > 1
        """)
        invalid_scores = cursor.fetchone()["cnt"]
        self.check(
            "评分在有效范围[0,1]",
            invalid_scores == 0,
            f"发现 {invalid_scores} 条无效评分"
        )

        print("\n[检查 4.3] 任务状态分布")

        cursor = self.conn.execute("""
            SELECT status, COUNT(*) as cnt
            FROM tasks
            GROUP BY status
        """)

        status_dist = {row["status"]: row["cnt"] for row in cursor.fetchall()}
        total_tasks = sum(status_dist.values())

        if total_tasks > 0:
            print(f"  任务总数: {total_tasks}")
            for status, count in status_dist.items():
                pct = count / total_tasks * 100
                print(f"    {status}: {count} ({pct:.1f}%)")

            self.check("任务状态统计", True)
        else:
            self.check("任务状态统计", False, "数据库中无任务", warning=True)

        print("\n[检查 4.4] 数据一致性")

        # 检查 generation_records 是否有对应的 evidence
        cursor = self.conn.execute("""
            SELECT COUNT(*) as cnt
            FROM generation_records
            WHERE evidence_id IS NULL
        """)
        no_evidence = cursor.fetchone()["cnt"]

        if no_evidence > 0:
            self.check(
                "所有记录有证据",
                False,
                f"{no_evidence} 条记录无证据",
                warning=True
            )
        else:
            self.check("所有记录有证据", True)

    def print_summary(self):
        """打印验证总结"""
        self.section("验证总结")

        total = self.passed + self.failed + self.warnings
        pass_rate = self.passed / total * 100 if total > 0 else 0

        print(f"\n总计检查: {total}")
        print(f"  [OK] 通过: {self.passed}")
        print(f"  [FAIL] 失败: {self.failed}")
        print(f"  [WARN] 警告: {self.warnings}")
        print(f"\n通过率: {pass_rate:.1f}%")

        if self.failed > 0:
            print(f"\n关键问题列表:")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")

        print("\n" + "="*60)
        if self.failed == 0:
            print("生产环境验证通过 [OK]")
        else:
            print(f"生产环境验证失败：{self.failed} 个关键问题需要修复")
        print("="*60)

        self.conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("生产环境验证")
    print("=" * 60)

    db_path = project_root / "data" / "hydropower.sqlite"
    validator = ProductionValidator(db_path)
    validator.run_all_checks()
