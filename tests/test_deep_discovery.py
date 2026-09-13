"""测试任务 4.2：Discovery Level 4 - 深度探索

验证：
1. Sitemap URL生成
2. Sitemap XML解析（Mock）
3. Sitemap过滤逻辑
4. 网站导航爬取（Mock）
5. 导航链接过滤
6. 完整流程（Mock）
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.discovery.sitemap_explorer import SitemapExplorer, SitemapConfig
from hydro_platform.discovery.navigation_crawler import NavigationCrawler, NavigationConfig
from unittest.mock import Mock, patch


def test_sitemap_url_generation():
    """测试Sitemap URL生成"""
    print("\n=== 测试 1: Sitemap URL生成 ===")

    explorer = SitemapExplorer()
    urls = explorer._get_sitemap_urls('https://www.example.com')

    assert len(urls) > 0, "应生成多个sitemap URL"
    assert any('sitemap.xml' in url for url in urls), "应包含sitemap.xml"
    assert any('sitemap_index.xml' in url for url in urls), "应包含sitemap_index.xml"

    print(f"[OK] 生成 {len(urls)} 个sitemap URL:")
    for url in urls[:3]:
        print(f"  - {url}")

    return True


def test_sitemap_parsing_mock():
    """测试Sitemap解析（Mock）"""
    print("\n=== 测试 2: Sitemap解析（Mock）===")

    explorer = SitemapExplorer()

    # Mock sitemap XML响应
    mock_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://www.example.com/annual-report-2023.pdf</loc>
    </url>
    <url>
        <loc>https://www.example.com/investor-relations/reports/2023</loc>
    </url>
    <url>
        <loc>https://www.example.com/about-us</loc>
    </url>
</urlset>"""

    with patch('requests.get') as mock_get:
        mock_get.return_value.content = mock_xml
        mock_get.return_value.raise_for_status = Mock()

        urls = explorer._parse_sitemap('https://www.example.com/sitemap.xml')

        assert len(urls) == 3, f"应解析出3个URL，实际{len(urls)}"
        assert 'annual-report-2023.pdf' in urls[0], "应包含PDF报告"
        print(f"[OK] 解析出 {len(urls)} 个URL")
        for url in urls:
            print(f"  - {url}")

    return True


def test_sitemap_filtering():
    """测试Sitemap URL过滤"""
    print("\n=== 测试 3: Sitemap URL过滤 ===")

    explorer = SitemapExplorer()

    urls = [
        'https://www.example.com/annual-report-2023.pdf',
        'https://www.example.com/generation-data-2023.html',
        'https://www.example.com/about-us',  # 无关
        'https://www.example.com/contact',    # 无关
        'https://www.example.com/statistics/2023',
    ]

    filtered = explorer._filter_relevant_urls(urls, year=2023, metric='generation')

    assert len(filtered) >= 3, f"应过滤出至少3个相关URL，实际{len(filtered)}"
    assert any('report' in url for url in filtered), "应包含报告链接"
    assert any('generation' in url for url in filtered), "应包含发电量链接"

    print(f"[OK] 过滤后保留 {len(filtered)} 个相关URL:")
    for url in filtered:
        print(f"  - {url}")

    return True


def test_sitemap_full_flow():
    """测试Sitemap完整流程（Mock）"""
    print("\n=== 测试 4: Sitemap完整流程（Mock）===")

    explorer = SitemapExplorer()

    mock_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://www.example.com/report-2023.pdf</loc></url>
    <url><loc>https://www.example.com/generation-statistics-2023.html</loc></url>
</urlset>"""

    with patch('requests.get') as mock_get:
        mock_get.return_value.content = mock_xml
        mock_get.return_value.raise_for_status = Mock()

        candidates = explorer.explore('https://www.example.com', year=2023, metric='generation')

        assert len(candidates) >= 1, f"应发现至少1个候选，实际{len(candidates)}"
        assert all(c.source_type == 'sitemap' for c in candidates), "来源类型应为sitemap"

        print(f"[OK] 发现 {len(candidates)} 个候选来源:")
        for c in candidates[:3]:
            print(f"  - {c.url}")
            print(f"    类型: {c.document_type}, 可靠性: {c.estimated_reliability:.2f}")

    return True


def test_navigation_crawling_mock():
    """测试导航爬取（Mock）"""
    print("\n=== 测试 5: 导航爬取（Mock）===")

    crawler = NavigationCrawler()

    # Mock首页HTML响应
    mock_html = b"""
    <html>
    <body>
        <nav>
            <a href="/about-us">About Us</a>
            <a href="/investor-relations">Investor Relations</a>
            <a href="/annual-reports">Annual Reports</a>
            <a href="/contact">Contact</a>
        </nav>
    </body>
    </html>
    """

    with patch('requests.get') as mock_get:
        mock_get.return_value.content = mock_html
        mock_get.return_value.raise_for_status = Mock()

        links = crawler._crawl_navigation('https://www.example.com')

        assert len(links) >= 3, f"应提取至少3个链接，实际{len(links)}"
        assert any('investor' in link['text'].lower() for link in links), "应包含投资者关系链接"
        assert any('report' in link['text'].lower() for link in links), "应包含报告链接"

        print(f"[OK] 提取 {len(links)} 个导航链接:")
        for link in links[:5]:
            print(f"  - {link['text']}: {link['url']}")

    return True


def test_navigation_filtering():
    """测试导航链接过滤"""
    print("\n=== 测试 6: 导航链接过滤 ===")

    crawler = NavigationCrawler()

    links = [
        {'url': 'https://www.example.com/investor-relations', 'text': 'Investor Relations'},
        {'url': 'https://www.example.com/annual-reports', 'text': 'Annual Reports'},
        {'url': 'https://www.example.com/about-us', 'text': 'About Us'},
        {'url': 'https://www.example.com/contact', 'text': 'Contact'},
        {'url': 'https://www.example.com/data-center', 'text': 'Data Center'},
    ]

    filtered = crawler._filter_relevant_links(links, year=2023, metric='generation')

    assert len(filtered) >= 2, f"应过滤出至少2个相关链接，实际{len(filtered)}"
    assert any('investor' in url.lower() or 'report' in url.lower() for url in filtered), "应包含相关链接"

    print(f"[OK] 过滤后保留 {len(filtered)} 个相关链接:")
    for url in filtered:
        print(f"  - {url}")

    return True


def test_navigation_full_flow():
    """测试导航爬取完整流程（Mock）"""
    print("\n=== 测试 7: 导航爬取完整流程（Mock）===")

    crawler = NavigationCrawler()

    mock_html = b"""
    <html>
    <body>
        <nav class="main-nav">
            <a href="/investor-relations">Investor Relations</a>
            <a href="/annual-reports">Annual Reports</a>
            <a href="/sustainability-report-2023.pdf">Sustainability Report 2023</a>
        </nav>
    </body>
    </html>
    """

    with patch('requests.get') as mock_get:
        mock_get.return_value.content = mock_html
        mock_get.return_value.raise_for_status = Mock()

        candidates = crawler.crawl('https://www.example.com', year=2023, metric='generation')

        assert len(candidates) >= 1, f"应发现至少1个候选，实际{len(candidates)}"
        assert all(c.source_type == 'navigation' for c in candidates), "来源类型应为navigation"

        print(f"[OK] 发现 {len(candidates)} 个候选来源:")
        for c in candidates[:3]:
            print(f"  - {c.url}")
            print(f"    类型: {c.document_type}, 可靠性: {c.estimated_reliability:.2f}")

    return True


def test_config():
    """测试配置"""
    print("\n=== 测试 8: 配置 ===")

    # Sitemap配置
    timeout = SitemapConfig.get_default_timeout()
    max_urls = SitemapConfig.get_max_urls_per_site()
    print(f"[OK] Sitemap配置: timeout={timeout}s, max_urls={max_urls}")

    # 导航爬取配置
    nav_timeout = NavigationConfig.get_default_timeout()
    max_depth = NavigationConfig.get_default_max_depth()
    max_links = NavigationConfig.get_max_links_per_page()
    print(f"[OK] 导航配置: timeout={nav_timeout}s, max_depth={max_depth}, max_links={max_links}")

    return True


def test_reliability_scoring():
    """测试可靠性评分"""
    print("\n=== 测试 9: 可靠性评分 ===")

    explorer = SitemapExplorer()

    test_cases = [
        ('https://energy.gov/report.pdf', 'pdf', 0.85),
        ('https://example.com/report.html', 'html', 0.65),
    ]

    for url, doc_type, min_expected in test_cases:
        score = explorer._estimate_reliability(url, doc_type)
        assert score >= min_expected, f"{url} 可靠性应 >= {min_expected}，实际 {score}"
        print(f"[OK] {url} ({doc_type}): {score:.2f}")

    return True


def main():
    print("=" * 60)
    print("任务 4.2: Discovery Level 4 - 深度探索测试")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("Sitemap URL生成", test_sitemap_url_generation()))
    results.append(("Sitemap解析Mock", test_sitemap_parsing_mock()))
    results.append(("Sitemap过滤", test_sitemap_filtering()))
    results.append(("Sitemap完整流程", test_sitemap_full_flow()))
    results.append(("导航爬取Mock", test_navigation_crawling_mock()))
    results.append(("导航链接过滤", test_navigation_filtering()))
    results.append(("导航完整流程", test_navigation_full_flow()))
    results.append(("配置", test_config()))
    results.append(("可靠性评分", test_reliability_scoring()))

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
        print("\n[OK] 任务 4.2 深度探索实现完成")
        print("\n功能说明:")
        print("  - Sitemap解析：从sitemap.xml提取报告和数据链接")
        print("  - 网站导航爬取：从首页导航发现报告页面")
        print("  - 智能过滤：基于关键词和年份过滤相关链接")
        print("  - 可靠性评估：根据域名和文档类型评分")
        print("  - 支持二级页面深度爬取（可配置）")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
