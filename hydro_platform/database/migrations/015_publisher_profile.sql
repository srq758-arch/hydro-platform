-- Migration 015: 可审计 Publisher Profile V1。
--
-- 本迁移只创建画像及其“成功来源观察”关系，不从历史 sources 自动回填，
-- 也不修改任何来源、候选或事实。画像只能由后续实际成功的 official 来源
-- 写入，或者由显式的运维回填工具写入（后者不在本迁移中执行）。

CREATE TABLE IF NOT EXISTS publisher_profiles (
    publisher_profile_id   TEXT PRIMARY KEY,
    canonical_name         TEXT NOT NULL,
    country                TEXT,
    publisher_type         TEXT NOT NULL,
    official_domain        TEXT NOT NULL,
    language               TEXT,
    report_path_patterns_json TEXT NOT NULL DEFAULT '[]',
    search_patterns_json   TEXT NOT NULL DEFAULT '[]',
    reliability_score      REAL NOT NULL DEFAULT 0.5
        CHECK (reliability_score >= 0.0 AND reliability_score <= 1.0),
    success_count          INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    last_success_at        TEXT,
    verification_basis     TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    UNIQUE (official_domain, country)
);

CREATE INDEX IF NOT EXISTS idx_publisher_profiles_domain
    ON publisher_profiles(official_domain, reliability_score DESC);
CREATE INDEX IF NOT EXISTS idx_publisher_profiles_country
    ON publisher_profiles(country, publisher_type);

CREATE TABLE IF NOT EXISTS publisher_profile_observations (
    publisher_profile_id   TEXT NOT NULL,
    source_id              TEXT NOT NULL,
    entity_id              TEXT NOT NULL,
    observed_url           TEXT NOT NULL,
    observed_at            TEXT NOT NULL,
    PRIMARY KEY (publisher_profile_id, source_id),
    FOREIGN KEY (publisher_profile_id) REFERENCES publisher_profiles(publisher_profile_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id),
    FOREIGN KEY (entity_id) REFERENCES stations(entity_id)
);

CREATE INDEX IF NOT EXISTS idx_publisher_profile_observations_entity
    ON publisher_profile_observations(entity_id, observed_at DESC);
