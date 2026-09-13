-- Migration 009: 来源发现台账。
-- ``sources`` 只保存已实际采集并可复用的来源；自动发现 URL 必须先进入候选台账。

CREATE TABLE IF NOT EXISTS source_discoveries (
    discovery_id          TEXT PRIMARY KEY,
    entity_id             TEXT NOT NULL,
    gem_wiki_url          TEXT,
    candidate_url         TEXT NOT NULL,
    canonical_url         TEXT NOT NULL,
    link_text             TEXT,
    section_title         TEXT,
    source_type           TEXT NOT NULL DEFAULT 'reference',
    document_type         TEXT NOT NULL DEFAULT 'html',
    discovery_method      TEXT NOT NULL,
    match_reason          TEXT,
    estimated_reliability REAL,
    task_fit_score        REAL,
    combined_score        REAL,
    status                TEXT NOT NULL DEFAULT 'discovered',
    error                 TEXT,
    discovered_at         TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    FOREIGN KEY (entity_id) REFERENCES stations(entity_id),
    UNIQUE (entity_id, canonical_url)
);

CREATE INDEX IF NOT EXISTS idx_source_discoveries_entity
    ON source_discoveries(entity_id, combined_score DESC);
CREATE INDEX IF NOT EXISTS idx_source_discoveries_status
    ON source_discoveries(status);
