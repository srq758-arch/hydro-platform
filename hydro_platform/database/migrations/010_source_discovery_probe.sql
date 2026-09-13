-- Migration 010: 为发现候选保存轻量访问探测结果。
-- 候选仅在访问探测通过（或明确需浏览器回退）时才可出现在采集入口。

ALTER TABLE source_discoveries ADD COLUMN access_status TEXT NOT NULL DEFAULT 'unverified';
ALTER TABLE source_discoveries ADD COLUMN http_status INTEGER;
ALTER TABLE source_discoveries ADD COLUMN final_url TEXT;
ALTER TABLE source_discoveries ADD COLUMN checked_at TEXT;

CREATE INDEX IF NOT EXISTS idx_source_discoveries_access
    ON source_discoveries(entity_id, access_status, combined_score DESC);
