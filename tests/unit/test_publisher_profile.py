"""Publisher Profile V1 只接收真实成功的官方来源。"""

from pathlib import Path

from hydro_platform.database.connection import connect
from hydro_platform.database.migrations import migrate, verify_publisher_profile_v15
from hydro_platform.discovery.identity_profile import build_station_identity_profile
from hydro_platform.discovery.publisher_profile import PublisherProfileRepository
from hydro_platform.intelligence.source_discovery_service import SourceDiscoveryService
from hydro_platform.registry.source_registry import SourceRegistry


def _station(db):
    db.execute(
        """INSERT INTO stations(entity_id, canonical_name, country)
           VALUES ('station-publisher', 'Test Hydropower Station', 'China')"""
    )
    db.commit()


def test_successful_official_source_builds_auditable_publisher_profile(db):
    _station(db)
    db.execute(
        """INSERT INTO sources(
               source_id, entity_id, url, source_url, canonical_url, publisher,
               language, source_type, source_reliability_score, success_count, last_success
           ) VALUES ('official-profile-source', 'station-publisher',
                     'https://www.operator.example/reports/2024/generation.pdf',
                     'https://www.operator.example/reports/2024/generation.pdf',
                     'https://www.operator.example/reports/2024/generation.pdf',
                     'Test Power Corporation', 'zh', 'official', 0.91, 2,
                     '2026-09-14T01:00:00Z')"""
    )
    db.commit()
    repo = PublisherProfileRepository(db)

    profile = repo.record_success('official-profile-source')

    assert profile is not None
    assert profile.canonical_name == 'Test Power Corporation'
    assert profile.official_domain == 'operator.example'
    assert profile.country == 'China'
    assert profile.report_path_patterns == ('/reports/{year}/generation.pdf',)
    assert profile.reliability_score == 0.91
    observation = db.execute(
        "SELECT entity_id, observed_url FROM publisher_profile_observations"
    ).fetchone()
    assert tuple(observation) == (
        'station-publisher', 'https://www.operator.example/reports/2024/generation.pdf',
    )

    station = dict(db.execute("SELECT * FROM stations WHERE entity_id='station-publisher'").fetchone())
    identity = build_station_identity_profile(db, station)
    assert identity.publisher_profiles[0]['canonical_name'] == 'Test Power Corporation'
    assert identity.publisher_profiles[0]['report_path_patterns'] == ['/reports/{year}/generation.pdf']
    intent = SourceDiscoveryService.build_generation_intent(identity.station_context(), '2024')
    assert any('Test Power Corporation' in query for query in intent.query_hints)


def test_non_official_or_unsuccessful_source_cannot_create_publisher_profile(db):
    _station(db)
    db.execute(
        """INSERT INTO sources(
               source_id, entity_id, url, source_url, canonical_url, source_type,
               success_count, last_success
           ) VALUES
           ('reference-source', 'station-publisher', 'https://reference.example/2024.pdf',
            'https://reference.example/2024.pdf', 'https://reference.example/2024.pdf',
            'reference', 9, '2026-09-14T01:00:00Z'),
           ('unproven-official-source', 'station-publisher', 'https://operator.example/2024.pdf',
            'https://operator.example/2024.pdf', 'https://operator.example/2024.pdf',
            'official', 0, NULL)"""
    )
    db.commit()
    repo = PublisherProfileRepository(db)

    assert repo.record_success('reference-source') is None
    assert repo.record_success('unproven-official-source') is None
    assert repo.profiles_for_entity('station-publisher') == []


def test_source_registry_success_event_updates_profile_only_after_success(db):
    _station(db)
    registry = SourceRegistry(db)
    source_id = registry.register_new_source('station-publisher', 'https://operator.example/reports/2024.pdf', {
        'source_type': 'official', 'publisher': 'Operator Group', 'language': 'en',
        'covered_metric': 'generation', 'covered_year': 2024,
    })
    repo = PublisherProfileRepository(db)
    assert repo.profiles_for_entity('station-publisher') == []

    registry.update_success(source_id, document_id='document-ok')

    profiles = repo.profiles_for_entity('station-publisher')
    assert len(profiles) == 1
    assert profiles[0].canonical_name == 'Operator Group'
    assert profiles[0].official_domain == 'operator.example'


def test_v15_migration_creates_empty_profile_tables_without_backfilling_history(tmp_path):
    """升级只增加结构，不把历史来源猜成经验证发布方。"""
    conn = connect(tmp_path / 'v15_profile.db')
    try:
        schema = (Path(__file__).parents[2] / 'hydro_platform' / 'database' / 'schema.sql').read_text(encoding='utf-8')
        conn.executescript(schema)
        assert migrate(conn, target_version=14) == 14
        conn.execute(
            """INSERT INTO stations(entity_id, canonical_name, country)
               VALUES ('legacy-station', 'Legacy Station', 'China')"""
        )
        conn.execute(
            """INSERT INTO sources(
                   source_id, entity_id, url, source_url, canonical_url, source_type,
                   success_count, last_success
               ) VALUES ('legacy-source', 'legacy-station', 'https://legacy.example/2023.pdf',
                         'https://legacy.example/2023.pdf', 'https://legacy.example/2023.pdf',
                         'official', 5, '2024-01-01T00:00:00Z')"""
        )
        conn.commit()

        assert migrate(conn, target_version=15) == 15
        assert verify_publisher_profile_v15(conn)[0] is True
        assert conn.execute('SELECT COUNT(*) FROM publisher_profiles').fetchone()[0] == 0
        assert tuple(conn.execute(
            "SELECT source_type, success_count, last_success FROM sources WHERE source_id='legacy-source'"
        ).fetchone()) == ('official', 5, '2024-01-01T00:00:00Z')
    finally:
        conn.close()
