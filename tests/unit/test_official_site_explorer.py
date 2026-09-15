"""已验证官网的有界导航 / sitemap 发现行为。"""

from hydro_platform.discovery.official_site_explorer import (
    FetchedOfficialPage,
    OfficialSiteExplorer,
)


def _fetcher(pages):
    def fetch(url):
        return pages.get(url, FetchedOfficialPage(404, "text/html", "", url))
    return fetch


def test_explorer_follows_only_same_domain_report_navigation_and_returns_document_candidate():
    pages = {
        "https://operator.example/news/verified-entry": FetchedOfficialPage(
            200, "text/html", """
                <a href='/investors/reports'>投资者报告</a>
                <a href='https://untrusted.example/2024.pdf'>外部 PDF</a>
            """, "https://operator.example/news/verified-entry",
        ),
        "https://operator.example/investors/reports": FetchedOfficialPage(
            200, "text/html", """
                <a href='/downloads/annual-generation-2024.pdf'>2024 年发电量年度报告</a>
            """, "https://operator.example/investors/reports",
        ),
    }
    found = OfficialSiteExplorer(fetch=_fetcher(pages), max_pages=4).discover(
        official_domains=["operator.example"],
        official_entry_urls=["https://operator.example/news/verified-entry"],
        target_period="2024",
    )

    assert [item["url"] for item in found] == ["https://operator.example/downloads/annual-generation-2024.pdf"]
    assert found[0]["discovery_method"] == "official_site_navigation"
    assert found[0]["metadata"]["parent_url"] == "https://operator.example/investors/reports"
    assert found[0]["metadata"]["discovery_depth"] == 2


def test_explorer_reads_same_domain_sitemap_but_never_uses_external_urls():
    pages = {
        "https://operator.example/sitemap.xml": FetchedOfficialPage(
            200, "application/xml", """
                <urlset>
                  <url><loc>https://operator.example/files/2024-generation.xlsx</loc></url>
                  <url><loc>https://untrusted.example/files/2024-generation.xlsx</loc></url>
                </urlset>
            """, "https://operator.example/sitemap.xml",
        ),
    }
    found = OfficialSiteExplorer(fetch=_fetcher(pages), max_pages=3).discover(
        official_domains=["operator.example"], target_period="2024",
    )

    assert [item["url"] for item in found] == ["https://operator.example/files/2024-generation.xlsx"]
    assert found[0]["discovery_method"] == "official_site_sitemap"


def test_explorer_uses_only_verified_report_path_pattern_as_a_candidate_not_a_success():
    explorer = OfficialSiteExplorer(fetch=_fetcher({}), max_pages=2)

    found = explorer.discover(
        official_domains=["operator.example"],
        known_report_paths={"operator.example": ["/reports/{year}/generation.pdf"]},
        target_period="2024",
    )

    assert found[0]["url"] == "https://operator.example/reports/2024/generation.pdf"
    assert found[0]["discovery_method"] == "official_site_known_report_path"
    assert found[0]["metadata"]["parent_url"] == "https://operator.example/"
    # Explorer 没有下载 PDF；后续 UrlProbe 和相关性门槛才决定是否能使用。
    assert found[0]["document_type"] == "pdf"
