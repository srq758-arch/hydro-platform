"""GEM Wiki 外部链接发现：全程离线，不访问真实网站。"""

from hydro_platform.discovery.ledger import SourceDiscoveryLedger
from hydro_platform.discovery.official import OfficialSourceFinder
from hydro_platform.reliability.scorer import ReliabilityScorer


GEM_HTML = """
<html><body>
  <h2>References</h2>
  <ul>
    <li><a href="https://operator.example.com/reports/2024.pdf?utm_source=gem">Official annual report</a></li>
    <li><a href="https://energy.gov.example/statistics">Government statistics</a></li>
    <li><a href="https://www.gem.wiki/Other_page">Another GEM page</a></li>
    <li><a href="https://globalenergymonitor.org/projects/global-hydropower-tracker">GEM tracker</a></li>
    <li><a href="https://web.archive.org/web/20240101/https://operator.example.com/report.pdf">Archived report</a></li>
    <li><a href="https://facebook.com/operator">Social page</a></li>
    <li><a href="mailto:data@example.com">Contact</a></li>
  </ul>
  <h2>Related projects</h2>
  <a href="https://ignored.example.com">Ignored after references</a>
</body></html>
"""


def _station(db, entity_id="station_gem"):
    db.execute(
        """INSERT INTO stations (entity_id, canonical_name, country, gem_wiki_url)
           VALUES (?, 'Example Dam', 'Exampleland', 'https://www.gem.wiki/Example_Dam')""",
        (entity_id,),
    )
    db.commit()


def test_extracts_traceable_external_links_and_filters_noise(db):
    _station(db)
    finder = OfficialSourceFinder(db, fetch_html=lambda _: GEM_HTML)

    candidates = finder.find({
        "entity_id": "station_gem", "entity_name": "Example Dam",
        "target_period": "2024", "metric": "generation",
    })

    urls = [item.url for item in candidates]
    assert urls == [
        "https://energy.gov.example/statistics",
        "https://operator.example.com/reports/2024.pdf",
    ]
    official = next(item for item in candidates if item.source_type == "official")
    assert official.link_text == "Official annual report"
    assert official.section_title == "References"
    assert official.discovery_method == "gem_wiki_external_link"
    assert official.canonical_url.endswith("2024.pdf")


def test_discovery_ledger_is_idempotent_and_does_not_touch_sources(db):
    _station(db)
    finder = OfficialSourceFinder(db, fetch_html=lambda _: GEM_HTML)
    candidates = [item.to_dict() for item in finder.find({
        "entity_id": "station_gem", "entity_name": "Example Dam",
        "target_period": "2024", "metric": "generation",
    })]
    ranked = ReliabilityScorer().rank_sources(candidates, {
        "entity_name": "Example Dam", "target_period": "2024", "metric": "generation",
    })
    ledger = SourceDiscoveryLedger(db)

    first = ledger.record_candidates(
        entity_id="station_gem", gem_wiki_url="https://www.gem.wiki/Example_Dam", candidates=ranked,
    )
    second = ledger.record_candidates(
        entity_id="station_gem", gem_wiki_url="https://www.gem.wiki/Example_Dam", candidates=ranked,
    )

    assert len(first) == len(second) == 2
    assert db.execute("SELECT COUNT(*) FROM source_discoveries").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    assert ledger.list_for_entity("station_gem")[0]["combined_score"] >= 0
