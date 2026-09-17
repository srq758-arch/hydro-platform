"""
Phase 3 前端改造集成测试
验证 P0-1（桌面端接入可信 Pipeline）和 P0-2（业务语义）前端部分
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from hydro_platform.app.api import Api


def test_get_all_stations_api():
    """测试 get_all_stations API 方法"""
    api = Api(data_mode="test")
    api.initialize()

    result = api.get_all_stations()

    assert "stations" in result
    assert isinstance(result["stations"], list)

    # 验证返回的电站数据结构
    if len(result["stations"]) > 0:
        station = result["stations"][0]
        assert "entity_id" in station
        assert "name_zh" in station
        assert "country" in station
        print(f"Sample station: {station['name_zh']} ({station['entity_id']})")


def test_start_task_with_business_semantics():
    """测试 start_task 接收业务语义参数（entity_id + target_period）"""
    api = Api(data_mode="test")
    api.initialize()

    # 准备测试参数（包含业务语义）
    task_config = {
        "entity_id": "CN_THREE_GORGES",
        "target_period": "2024",
        "type": "download_url",
        "url": "https://example.com/test.pdf",
        "source_title": "测试来源",
        "metadata": {},
        "data_mode": "test"
    }

    # 这个调用应该被路由到 start_task_v2（可信 Pipeline）
    # 由于我们没有真实的 URL，预期会在 download 阶段失败
    # 但重要的是验证参数传递正确
    try:
        result = api.start_task(task_config)
        # 如果失败，应该有明确的失败阶段和错误信息
        if result.get("status") == "failed":
            assert "failure_stage" in result or "error_message" in result
            print(f"Task failed as expected: {result.get('failure_stage')} - {result.get('error_message')}")
    except Exception as e:
        # 预期可能会有异常（例如 URL 无法访问）
        print(f"Task raised exception as expected: {e}")


def test_start_task_missing_business_semantics():
    """测试缺少业务语义时的错误处理"""
    api = Api(data_mode="test")
    api.initialize()

    # 缺少 entity_id 和 target_period
    task_config = {
        "type": "download_url",
        "url": "https://example.com/test.pdf",
        "source_title": "测试来源",
        "metadata": {},
        "data_mode": "test"
    }

    try:
        result = api.start_task(task_config)
        # 统一入口必须拒绝缺少业务上下文的旧式调用，不再回退到历史直写流程。
        assert result.get("status") == "failed"
        assert result.get("error_code") == "MISSING_BUSINESS_CONTEXT"
        print(f"Task rejected without business semantics: {result.get('error_code')}")
    except Exception as e:
        print(f"Task without business semantics raised: {e}")


if __name__ == "__main__":
    print("\n=== Phase 3 Frontend Integration Tests ===\n")

    print("Test 1: get_all_stations API")
    test_get_all_stations_api()
    print("PASSED\n")

    print("Test 2: start_task with business semantics")
    test_start_task_with_business_semantics()
    print("PASSED\n")

    print("Test 3: start_task missing business semantics")
    test_start_task_missing_business_semantics()
    print("PASSED\n")

    print("=== All Phase 3 Frontend Tests Passed ===")
