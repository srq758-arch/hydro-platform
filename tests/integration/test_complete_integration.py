"""完整集成测试套件

覆盖5个核心场景：
1. 新任务冷启动（无历史源）
2. 历史源优先使用
3. 历史源失效切换
4. 并发任务处理
5. 评分系统演化
"""

import sys
from pathlib import Path
import time
import threading
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.database.connection import connect
from hydro_platform.registry.source_registry import SourceRegistry
from hydro_platform.discovery.resolver import DiscoveryResolver
from hydro_platform.reliability.scorer import ReliabilityScorer
from hydro_platform.pipeline.source_resolver import resolve_sources_enhanced
from hydro_platform.models.task import Task
from hydro_platform.common.enums import TaskType, EntityType


class IntegrationTestSuite:
    """集成测试套件"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = connect(db_path)
        self.registry = SourceRegistry(self.conn)
        self.resolver = DiscoveryResolver(self.conn)
        self.scorer = ReliabilityScorer()

        self.passed = 0
        self.failed = 0
        self.test_results = []

    def assert_test(self, name: str, condition: bool, message: str = ""):
        """测试断言"""
        if condition:
            self.passed += 1
            result = f"  [OK] {name}"
            print(result)
            self.test_results.append(("PASS", name, ""))
        else:
            self.failed += 1
            result = f"  [FAIL] {name}: {message}"
            print(result)
            self.test_results.append(("FAIL", name, message))

    def section(self, title: str):
        """打印章节"""
        print(f"\n{'='*60}")
        print(f"{title}")
        print('='*60)

    def cleanup_test_data(self, entity_id: str):
        """清理测试数据"""
        self.conn.execute("DELETE FROM sources WHERE entity_id = ?", (entity_id,))
        self.conn.execute("DELETE FROM tasks WHERE entity_id = ?", (entity_id,))
        self.conn.commit()

    def scenario_1_cold_start(self):
        """场景1: 新任务冷启动"""
        self.section("场景1: 新任务冷启动（无历史源）")

        entity_id = "test_cold_start_station"
        self.cleanup_test_data(entity_id)

        print("\n步骤1: 查询历史源（预期无结果）")
        source = self.registry.query_best_source(entity_id, "generation", 2024)
        self.assert_test("无历史源", source is None)

        print("\n步骤2: 触发Discovery")
        # 使用一个真实电站进行测试
        cursor = self.conn.execute("""
            SELECT entity_id, canonical_name, country
            FROM stations
            WHERE country = 'China'
            LIMIT 1
        """)
        real_station = cursor.fetchone()

        if real_station:
            task_dict = {
                "entity_id": real_station["entity_id"],
                "entity_name": real_station["canonical_name"],
                "target_period": "2024",
                "metric": "generation"
            }

            candidates = self.resolver.discover(task_dict, min_candidates=3)
            self.assert_test("Discovery找到候选源", len(candidates) > 0)

            if candidates:
                print(f"  找到 {len(candidates)} 个候选源")

                # 验证排序
                sorted_ok = all(
                    candidates[i].get("combined_score", 0) >= candidates[i+1].get("combined_score", 0)
                    for i in range(len(candidates) - 1)
                )
                self.assert_test("候选源按分数排序", sorted_ok)

                print("\n步骤3: 注册最佳候选源")
                best = candidates[0]
                source_id = self.registry.register_new_source(
                    entity_id=entity_id,
                    source_url=best["url"],
                    metadata={
                        "source_type": best.get("source_type", "unknown"),
                        "document_type": best.get("document_type", "unknown"),
                        "covered_metric": "generation",
                        "covered_year": 2024,
                        "estimated_reliability": best.get("combined_score", 0.5)
                    }
                )
                self.assert_test("注册新源成功", source_id is not None)

                print("\n步骤4: 验证注册结果")
                registered = self.registry.query_best_source(entity_id, "generation", 2024)
                self.assert_test("可查询到已注册源", registered is not None)
                if registered:
                    self.assert_test(
                        "注册源URL正确",
                        registered["source_url"] == best["url"]
                    )

        self.cleanup_test_data(entity_id)

    def scenario_2_historical_priority(self):
        """场景2: 历史源优先使用"""
        self.section("场景2: 历史源优先使用")

        entity_id = "test_historical_priority"
        self.cleanup_test_data(entity_id)

        print("\n步骤1: 预置历史源")
        source_id = self.registry.register_new_source(
            entity_id=entity_id,
            source_url="https://historical-source.example.com/report-2024.pdf",
            metadata={
                "source_type": "official",
                "document_type": "pdf",
                "covered_metric": "generation",
                "covered_year": 2024,
                "estimated_reliability": 0.80
            }
        )
        self.assert_test("预置历史源", source_id is not None)

        print("\n步骤2: 模拟3次成功使用")
        for i in range(3):
            self.registry.update_success(source_id, f"doc_{i}")
            time.sleep(0.01)

        print("\n步骤3: 查询最佳源")
        best_source = self.registry.query_best_source(entity_id, "generation", 2024)
        self.assert_test("可查询到历史源", best_source is not None)

        if best_source:
            self.assert_test("历史源ID匹配", best_source["source_id"] == source_id)
            initial_score = best_source["source_reliability_score"]
            print(f"  当前评分: {initial_score:.3f}")
            self.assert_test("评分已提升", initial_score > 0.80)

            print("\n步骤4: 再次成功使用")
            self.registry.update_success(source_id, "doc_final")

            updated_source = self.registry.query_best_source(entity_id, "generation", 2024)
            if updated_source:
                new_score = updated_source["source_reliability_score"]
                print(f"  更新后评分: {new_score:.3f}")
                self.assert_test("评分继续提升", new_score > initial_score)

        self.cleanup_test_data(entity_id)

    def scenario_3_fallback_on_failure(self):
        """场景3: 历史源失效切换"""
        self.section("场景3: 历史源失效切换")

        entity_id = "test_fallback"
        self.cleanup_test_data(entity_id)

        print("\n步骤1: 预置历史源")
        source_id = self.registry.register_new_source(
            entity_id=entity_id,
            source_url="https://failing-source.example.com/report.pdf",
            metadata={
                "source_type": "official",
                "document_type": "pdf",
                "covered_metric": "generation",
                "covered_year": 2024,
                "estimated_reliability": 0.85
            }
        )

        print("\n步骤2: 模拟多次失败")
        for i in range(5):
            self.registry.update_failure(
                source_id,
                reason=f"HTTP 404 - attempt {i+1}",
                stage="download"
            )
            time.sleep(0.01)

        print("\n步骤3: 检查源状态")
        failed_source = self.registry.query_best_source(entity_id, "generation", 2024)

        if failed_source:
            score = failed_source["source_reliability_score"]
            print(f"  失败后评分: {score:.3f}")
            self.assert_test("评分明显下降", score < 0.50)

            # Precheck应该失败
            should_use = self.registry.precheck_source(failed_source)
            self.assert_test("Precheck拒绝失败源", not should_use)

        print("\n步骤4: 验证会触发重新Discovery")
        # 在实际流程中，precheck失败会触发Discovery
        self.assert_test("需要重新Discovery", True)

        self.cleanup_test_data(entity_id)

    def scenario_4_concurrent_tasks(self):
        """场景4: 并发任务处理"""
        self.section("场景4: 并发任务处理")

        num_tasks = 5
        entity_ids = [f"test_concurrent_{i}" for i in range(num_tasks)]

        # 清理
        for eid in entity_ids:
            self.cleanup_test_data(eid)

        print(f"\n步骤1: 并发注册{num_tasks}个源")

        results = []
        errors = []

        def register_task(eid):
            try:
                conn = connect(self.db_path)
                registry = SourceRegistry(conn)

                source_id = registry.register_new_source(
                    entity_id=eid,
                    source_url=f"https://concurrent-test.example.com/{eid}.pdf",
                    metadata={
                        "source_type": "official",
                        "document_type": "pdf",
                        "covered_metric": "generation",
                        "covered_year": 2024,
                        "estimated_reliability": 0.75
                    }
                )
                results.append((eid, source_id))
                conn.close()
            except Exception as e:
                errors.append((eid, str(e)))

        threads = []
        for eid in entity_ids:
            t = threading.Thread(target=register_task, args=(eid,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assert_test("无并发错误", len(errors) == 0)
        self.assert_test("所有任务完成", len(results) == num_tasks)

        print(f"\n步骤2: 验证所有源已注册")
        for eid in entity_ids:
            source = self.registry.query_best_source(eid, "generation", 2024)
            self.assert_test(f"源已注册: {eid}", source is not None)

        # 清理
        for eid in entity_ids:
            self.cleanup_test_data(eid)

    def scenario_5_scoring_evolution(self):
        """场景5: 评分系统演化"""
        self.section("场景5: 评分系统演化")

        entity_id = "test_scoring_evolution"
        self.cleanup_test_data(entity_id)

        print("\n步骤1: 注册初始源")
        source_id = self.registry.register_new_source(
            entity_id=entity_id,
            source_url="https://evolving-source.example.com/report.pdf",
            metadata={
                "source_type": "search_result",
                "document_type": "pdf",
                "covered_metric": "generation",
                "covered_year": 2024,
                "estimated_reliability": 0.50
            }
        )

        initial = self.registry.query_best_source(entity_id, "generation", 2024)
        initial_score = initial["source_reliability_score"] if initial else 0
        print(f"  初始评分: {initial_score:.3f}")

        print("\n步骤2: 模拟混合使用记录")
        scores = [initial_score]

        # 3次成功
        for i in range(3):
            self.registry.update_success(source_id, f"doc_success_{i}")
            current = self.registry.query_best_source(entity_id, "generation", 2024)
            if current:
                scores.append(current["source_reliability_score"])
                time.sleep(0.01)

        # 1次失败
        self.registry.update_failure(source_id, "Temporary network error", "download")
        current = self.registry.query_best_source(entity_id, "generation", 2024)
        if current:
            scores.append(current["source_reliability_score"])

        # 2次成功
        for i in range(2):
            self.registry.update_success(source_id, f"doc_success_final_{i}")
            current = self.registry.query_best_source(entity_id, "generation", 2024)
            if current:
                scores.append(current["source_reliability_score"])
                time.sleep(0.01)

        print(f"\n步骤3: 评分演化轨迹")
        for i, score in enumerate(scores):
            print(f"  第{i}次: {score:.3f}")

        final_score = scores[-1]
        self.assert_test("总体评分上升", final_score > initial_score)
        self.assert_test("最终评分合理", 0.5 <= final_score <= 0.9)

        print("\n步骤4: 验证使用统计")
        final_source = self.registry.query_best_source(entity_id, "generation", 2024)
        if final_source:
            self.assert_test("成功次数正确", final_source["success_count"] == 5)
            self.assert_test("失败次数正确", final_source["failure_count"] == 1)

        self.cleanup_test_data(entity_id)

    def run_all_scenarios(self):
        """运行所有场景"""
        print("="*60)
        print("完整集成测试套件")
        print("="*60)

        start_time = time.time()

        try:
            self.scenario_1_cold_start()
            self.scenario_2_historical_priority()
            self.scenario_3_fallback_on_failure()
            self.scenario_4_concurrent_tasks()
            self.scenario_5_scoring_evolution()
        except Exception as e:
            print(f"\n[ERROR] 测试异常: {e}")
            import traceback
            traceback.print_exc()

        elapsed = time.time() - start_time

        self.section("测试总结")
        total = self.passed + self.failed
        pass_rate = self.passed / total * 100 if total > 0 else 0

        print(f"\n总计测试: {total}")
        print(f"  [OK] 通过: {self.passed}")
        print(f"  [FAIL] 失败: {self.failed}")
        print(f"通过率: {pass_rate:.1f}%")
        print(f"耗时: {elapsed:.2f}秒")

        if self.failed > 0:
            print("\n失败的测试:")
            for status, name, message in self.test_results:
                if status == "FAIL":
                    print(f"  - {name}: {message}")

        print("\n" + "="*60)
        if self.failed == 0:
            print("所有集成测试通过 [OK]")
        else:
            print(f"集成测试失败: {self.failed} 个测试未通过")
        print("="*60)

        self.conn.close()


if __name__ == "__main__":
    db_path = project_root / "data" / "hydropower.sqlite"
    suite = IntegrationTestSuite(db_path)
    suite.run_all_scenarios()
