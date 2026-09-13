"""测试任务 4.1：Discovery Level 3 - Google搜索引擎扩展

验证：
1. 查询构造（不同metric和参数组合）
2. Mock API响应解析
3. 文档类型推断
4. 可靠性评估
5. 完整流程（需要API密钥）
"""

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.discovery.google_search import GoogleSearchDiscovery, GoogleSearchConfig
from unittest.mock import Mock, patch


def test_query_construction():
    """测试搜索查询构造"""
    print("\n=== 测试 1: 搜索查询构造 ===")

    discovery = GoogleSearchDiscovery(api_key="test_key", search_engine_id="test_cx")

    # 测试1：发电量查询
    query1 = discovery._build_query(
        entity_name="Three Gorges Dam",
        country="CN",
        year=2023,
        metric="generation"
    )
    assert '"Three Gorges Dam"' in query1, "应包含引号包裹的电站名称"
    assert 'China' in query1, "应包含国家名称"
    assert '2023' in query1, "应包含年份"
    assert 'GWh' in query1 or 'TWh' in query1, "应包含发电量单位"
    print(f"[OK] 发电量查询: {query1}")

    # 测试2：容量查询
    query2 = discovery._build_query(
        entity_name="Itaipu Dam",
        country="BR",
        year=None,
        metric="capacity"
    )
    assert '"Itaipu Dam"' in query2, "应包含电站名称"
    assert 'Brazil' in query2, "应转换国家代码为名称"
    assert 'MW' in query2 or 'GW' in query2, "应包含容量单位"
    print(f"[OK] 容量查询: {query2}")

    # 测试3：无年份查询
    query3 = discovery._build_query(
        entity_name="Belo Monte",
        country="BR",
        year=None,
        metric="generation"
    )
    assert '"Belo Monte"' in query3, "应包含电站名称"
    assert '2023' not in query3, "不应包含年份"
    print(f"[OK] 无年份查询: {query3}")

    return True


def test_document_type_inference():
    """测试文档类型推断"""
    print("\n=== 测试 2: 文档类型推断 ===")

    discovery = GoogleSearchDiscovery(api_key="test_key", search_engine_id="test_cx")

    test_cases = [
        ("https://example.com/report.pdf", "pdf"),
        ("https://example.com/data.json", "json"),
        ("https://example.com/page.html", "html"),
        ("https://example.com/index", "html"),
        ("https://example.com/data.csv", "csv"),
    ]

    for url, expected in test_cases:
        result = discovery._guess_document_type(url)
        assert result == expected, f"URL {url} 应识别为 {expected}，实际为 {result}"
        print(f"[OK] {url} -> {result}")

    return True


def test_reliability_estimation():
    """测试可靠性评估"""
    print("\n=== 测试 3: 可靠性评估 ===")

    discovery = GoogleSearchDiscovery(api_key="test_key", search_engine_id="test_cx")

    test_cases = [
        ("https://energy.gov/report.pdf", "pdf", 0.85),  # 政府+PDF
        ("https://example.edu/paper.html", "html", 0.7),  # 教育机构
        ("https://unknown.com/page.html", "html", 0.5),   # 普通域名
        ("https://iea.org/data.json", "json", 0.7),       # 知名组织
    ]

    for url, doc_type, min_expected in test_cases:
        score = discovery._estimate_reliability(url, doc_type)
        assert score >= min_expected, f"{url} 可靠性应 >= {min_expected}，实际 {score}"
        print(f"[OK] {url} ({doc_type}): {score:.2f}")

    return True


def test_result_parsing():
    """测试搜索结果解析"""
    print("\n=== 测试 4: 搜索结果解析 ===")

    discovery = GoogleSearchDiscovery(api_key="test_key", search_engine_id="test_cx")

    # Mock搜索结果
    mock_item = {
        'title': 'Three Gorges Dam 2023 Annual Report',
        'link': 'https://www.ctg.com.cn/report-2023.pdf',
        'snippet': 'The dam generated 87.8 TWh of electricity in 2023...',
        'displayLink': 'www.ctg.com.cn'
    }

    candidate = discovery._to_source_candidate(mock_item, year=2023, metric='generation')

    assert candidate.url == mock_item['link'], "URL应匹配"
    assert candidate.source_type == 'search_result', "来源类型应为search_result"
    assert candidate.document_type == 'pdf', "应识别为PDF"
    assert candidate.covered_year == 2023, "年份应匹配"
    assert candidate.estimated_reliability > 0, "可靠性应>0"
    assert 'Google' in candidate.match_reason, "匹配原因应提及Google"

    print(f"[OK] 解析结果:")
    print(f"  URL: {candidate.url}")
    print(f"  类型: {candidate.document_type}")
    print(f"  可靠性: {candidate.estimated_reliability:.2f}")
    print(f"  匹配原因: {candidate.match_reason[:80]}...")

    return True


def test_api_call_mock():
    """测试API调用（Mock模式）"""
    print("\n=== 测试 5: API调用（Mock）===")

    discovery = GoogleSearchDiscovery(api_key="test_key", search_engine_id="test_cx")

    # Mock响应
    mock_response = {
        'items': [
            {
                'title': 'Dam Report 1',
                'link': 'https://example.com/report1.pdf',
                'snippet': 'Generation data for 2023...'
            },
            {
                'title': 'Dam Report 2',
                'link': 'https://example.edu/report2.html',
                'snippet': 'Annual statistics...'
            }
        ]
    }

    with patch('requests.get') as mock_get:
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = Mock()

        results = discovery._call_google_api("test query", limit=10)

        assert len(results) == 2, f"应返回2条结果，实际{len(results)}"
        assert results[0]['link'] == 'https://example.com/report1.pdf'
        print(f"[OK] Mock API返回 {len(results)} 条结果")

    return True


def test_full_workflow_mock():
    """测试完整流程（Mock模式）"""
    print("\n=== 测试 6: 完整流程（Mock）===")

    discovery = GoogleSearchDiscovery(api_key="test_key", search_engine_id="test_cx")

    task = {
        'entity_id': 'test_001',
        'entity_name': 'Three Gorges Dam',
        'country': 'CN',
        'target_period': 2023,  # 应该是int而不是str
        'metric': 'generation'
    }

    mock_response = {
        'items': [
            {
                'title': 'Three Gorges 2023 Report',
                'link': 'https://www.ctg.com.cn/report.pdf',
                'snippet': 'Generated 87.8 TWh in 2023'
            }
        ]
    }

    with patch('requests.get') as mock_get:
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = Mock()

        candidates = discovery.find(task, limit=5)

        assert len(candidates) == 1, f"应返回1个候选，实际{len(candidates)}"
        assert candidates[0].url == 'https://www.ctg.com.cn/report.pdf'
        assert candidates[0].covered_year == 2023
        print(f"[OK] 发现 {len(candidates)} 个候选来源")
        print(f"  - {candidates[0].url}")

    return True


def test_config_check():
    """测试配置检查"""
    print("\n=== 测试 7: 配置检查 ===")

    is_configured = GoogleSearchConfig.is_configured()
    print(f"[OK] Google搜索配置状态: {'已配置' if is_configured else '未配置'}")

    if is_configured:
        try:
            api_key, engine_id = GoogleSearchConfig.from_env()
            print(f"[OK] API Key: {api_key[:10]}...")
            print(f"[OK] Engine ID: {engine_id[:10]}...")
        except Exception as e:
            print(f"[WARN] 配置加载失败: {e}")
    else:
        print("[INFO] 需要设置环境变量:")
        print("  GOOGLE_API_KEY=your_api_key")
        print("  GOOGLE_SEARCH_ENGINE_ID=your_engine_id")

    return True


@pytest.mark.network
def test_real_api_call():
    """真实 Google API 冒烟测试；默认测试套件绝不执行网络访问。"""
    if not GoogleSearchConfig.is_configured():
        pytest.skip("未配置 Google API 凭据")

    api_key, engine_id = GoogleSearchConfig.from_env()
    discovery = GoogleSearchDiscovery(api_key, engine_id)
    task = {
        'entity_id': 'test_001',
        'entity_name': 'Three Gorges Dam',
        'country': 'CN',
        'target_period': '2023',
        'metric': 'generation'
    }
    candidates = discovery.find(task, limit=3)
    assert isinstance(candidates, list)


def main():
    print("=" * 60)
    print("任务 4.1: Discovery Level 3 - Google搜索引擎扩展测试")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("查询构造", test_query_construction()))
    results.append(("文档类型推断", test_document_type_inference()))
    results.append(("可靠性评估", test_reliability_estimation()))
    results.append(("结果解析", test_result_parsing()))
    results.append(("API调用Mock", test_api_call_mock()))
    results.append(("完整流程Mock", test_full_workflow_mock()))
    results.append(("配置检查", test_config_check()))
    results.append(("真实API调用", test_real_api_call()))

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "[OK] 通过" if result else "[FAIL] 失败"
        print(f"{status}: {name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n[OK] 任务 4.1 Google搜索引擎扩展实现完成")
        print("\n功能说明:")
        print("  - 支持构造发电量和容量搜索查询")
        print("  - 自动推断文档类型（PDF/HTML/JSON等）")
        print("  - 基于域名和文档类型评估可靠性")
        print("  - 返回标准SourceCandidate对象")
        print("  - 支持从环境变量加载API配置")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
