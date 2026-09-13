"""测试 Reliability Scorer 功能"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.reliability.scorer import ReliabilityScorer

def test_reliability_scorer():
    """测试 Reliability Scorer 三个评分功能"""

    print("=" * 60)
    print("测试 Reliability Scorer")
    print("=" * 60)

    scorer = ReliabilityScorer()

    # 测试1: 来源可靠性评分
    print("\n[测试1] 来源可靠性评分")

    # 测试政府域名
    score_gov = scorer.score_source_reliability(
        "https://www.eia.gov/electricity/annual/",
        source_type="authority"
    )
    print(f"EIA (.gov): {score_gov:.2f} (expected: 0.95)")
    assert score_gov == 0.95, f"Expected 0.95, got {score_gov}"

    # 测试可信域名
    score_ctg = scorer.score_source_reliability(
        "https://www.ctg.com.cn/sxjt/sxyw/202501/",
        source_type="official"
    )
    print(f"CTG (可信域名): {score_ctg:.2f} (expected: 0.90)")
    assert score_ctg == 0.90, f"Expected 0.90, got {score_ctg}"

    # 测试官方类型
    score_official = scorer.score_source_reliability(
        "https://example.com/report",
        source_type="official"
    )
    print(f"Official (未知域名): {score_official:.2f} (expected: 0.90-0.92)")
    assert 0.90 <= score_official <= 0.92, f"Expected 0.90-0.92, got {score_official}"

    # 测试搜索结果
    score_search = scorer.score_source_reliability(
        "https://news.example.com/article",
        source_type="search_result"
    )
    print(f"Search Result: {score_search:.2f} (expected: 0.40-0.43)")
    assert 0.40 <= score_search <= 0.43, f"Expected 0.40-0.43, got {score_search}"

    print("[OK] 来源可靠性评分测试通过")

    # 测试2: 任务适配度评分
    print("\n[测试2] 任务适配度评分")

    source = {
        "source_url": "https://example.com/annual-report-2024.pdf",
        "document_type": "pdf"
    }

    task = {
        "entity_name": "Three Gorges Dam",
        "target_period": "2024",
        "metric": "generation"
    }

    fit_score = scorer.score_task_fit(source, task)
    print(f"适配度评分: {fit_score:.2f}")
    print(f"  - URL包含年份2024: 应该+0.2")
    print(f"  - PDF文档: 应该+0.05")
    assert fit_score >= 0.70, f"Expected >= 0.70, got {fit_score}"

    print("[OK] 任务适配度评分测试通过")

    # 测试3: 记录置信度评分
    print("\n[测试3] 记录置信度评分")

    # 校验通过的候选
    candidate_good = {
        "generation_gwh": 100.5,
        "evidence_text": "The plant generated 100.5 GWh in 2024",
        "page_number": 42,
        "confidence": 0.9
    }

    validation_passed = {
        "passed": True,
        "issues": []
    }

    conf_score = scorer.score_record_confidence(candidate_good, validation_passed)
    print(f"校验通过的记录: {conf_score:.2f} (expected: >= 0.80)")
    assert conf_score >= 0.80, f"Expected >= 0.80, got {conf_score}"

    # 校验失败的候选
    candidate_bad = {
        "generation_gwh": 100.5,
        "confidence": 0.5
    }

    validation_failed = {
        "passed": False,
        "issues": [
            {"severity": "high", "message": "Value out of range"},
            {"severity": "medium", "message": "Missing unit"}
        ]
    }

    conf_score_bad = scorer.score_record_confidence(candidate_bad, validation_failed)
    print(f"校验失败的记录: {conf_score_bad:.2f} (expected: < 0.50)")
    assert conf_score_bad < 0.50, f"Expected < 0.50, got {conf_score_bad}"

    print("[OK] 记录置信度评分测试通过")

    # 测试4: 候选来源排序
    print("\n[测试4] 候选来源排序")

    candidates = [
        {
            "url": "https://news.example.com/article-2024",
            "source_type": "search_result"
        },
        {
            "url": "https://www.eia.gov/data/2024",
            "source_type": "authority"
        },
        {
            "url": "https://www.ctg.com.cn/report-2024.pdf",
            "source_type": "official"
        }
    ]

    task = {
        "entity_name": "Three Gorges",
        "target_period": "2024",
        "metric": "generation"
    }

    ranked = scorer.rank_sources(candidates, task)

    print(f"排序结果 (按综合评分降序):")
    for i, cand in enumerate(ranked, 1):
        print(f"  {i}. {cand['url']}")
        print(f"     可靠性: {cand['source_reliability_score']:.2f}, "
              f"适配度: {cand['task_fit_score']:.2f}, "
              f"综合: {cand['combined_score']:.2f}")

    # 验证排序正确性
    assert ranked[0]['combined_score'] >= ranked[1]['combined_score']
    assert ranked[1]['combined_score'] >= ranked[2]['combined_score']

    # 验证 EIA 或 CTG 应该排在第一位（高可靠性）
    top_url = ranked[0]['url']
    assert 'eia.gov' in top_url or 'ctg.com.cn' in top_url, \
        f"Expected high-reliability source at top, got {top_url}"

    print("[OK] 候选来源排序测试通过")

    print("\n" + "=" * 60)
    print("所有测试通过 [OK]")
    print("=" * 60)


if __name__ == "__main__":
    test_reliability_scorer()
