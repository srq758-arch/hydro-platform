-- 水电平台 SQLite schema（文档 16.4）。
-- 本期一次性建全 10 张表，唯一约束一次建对，避免后续迁移。
-- 约定：所有时间戳存 ISO8601 UTC 字符串；布尔用 0/1。

PRAGMA foreign_keys = ON;

-- 1) schema 版本表：migration runner 据此判断已应用版本
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- 2) 存量电站
CREATE TABLE IF NOT EXISTS stations (
    entity_id           TEXT PRIMARY KEY,
    entity_type         TEXT NOT NULL DEFAULT 'station',
    canonical_name      TEXT NOT NULL,
    aliases             TEXT,
    local_name          TEXT,
    country             TEXT,
    country_2           TEXT,
    region              TEXT,
    subregion           TEXT,
    state_province      TEXT,
    river               TEXT,
    latitude            REAL,
    longitude           REAL,
    location_accuracy   TEXT,
    capacity_mw         REAL,
    turbines            INTEGER,
    status              TEXT,
    technology          TEXT,
    operator            TEXT,
    owner               TEXT,
    commissioning_year  INTEGER,
    retired_year        INTEGER,
    gem_location_id     TEXT,
    gem_unit_id         TEXT,
    gem_wiki_url        TEXT,
    priority_tier       TEXT,
    collection_priority INTEGER,
    needs_review        INTEGER NOT NULL DEFAULT 0,
    source_seed         TEXT,
    source_url          TEXT,
    dataset_version     TEXT,
    registry_version    TEXT,
    raw_record_hash     TEXT
);
CREATE INDEX IF NOT EXISTS idx_stations_country ON stations(country);
CREATE INDEX IF NOT EXISTS idx_stations_tier ON stations(priority_tier);

-- 3) 新增项目
CREATE TABLE IF NOT EXISTS projects (
    entity_id           TEXT PRIMARY KEY,
    entity_type         TEXT NOT NULL DEFAULT 'project',
    canonical_name      TEXT NOT NULL,
    aliases             TEXT,
    local_name          TEXT,
    country             TEXT,
    country_2           TEXT,
    region              TEXT,
    subregion           TEXT,
    state_province      TEXT,
    river               TEXT,
    latitude            REAL,
    longitude           REAL,
    location_accuracy   TEXT,
    capacity_mw         REAL,
    turbines            INTEGER,
    status              TEXT,
    technology          TEXT,
    operator            TEXT,
    owner               TEXT,
    commissioning_year  INTEGER,
    gem_location_id     TEXT,
    gem_unit_id         TEXT,
    gem_wiki_url        TEXT,
    priority_tier       TEXT,
    collection_priority INTEGER,
    needs_review        INTEGER NOT NULL DEFAULT 0,
    source_seed         TEXT,
    source_url          TEXT,
    dataset_version     TEXT,
    registry_version    TEXT,
    raw_record_hash     TEXT
);
CREATE INDEX IF NOT EXISTS idx_projects_country ON projects(country);
CREATE INDEX IF NOT EXISTS idx_projects_tier ON projects(priority_tier);

-- 4) 任务表
CREATE TABLE IF NOT EXISTS tasks (
    task_id             TEXT PRIMARY KEY,
    entity_id           TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    task_type           TEXT NOT NULL,
    target_period       TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    priority_tier       TEXT,
    collection_priority INTEGER,
    attempts            INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 3,
    failure_stage       TEXT,
    last_error          TEXT,
    source_type         TEXT DEFAULT 'automatic',
    user_specified_source TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (entity_id, task_type, target_period)
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_tier ON tasks(priority_tier);
CREATE INDEX IF NOT EXISTS idx_tasks_source_type ON tasks(source_type);

-- 5) 来源表
CREATE TABLE IF NOT EXISTS sources (
    source_id       TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    title           TEXT,
    publisher       TEXT,
    publish_date    TEXT,
    retrieved_at    TEXT,
    content_hash    TEXT,
    archive_path    TEXT,
    language        TEXT,
    UNIQUE (url, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash);

-- 6) 发电量事实表（核心）
CREATE TABLE IF NOT EXISTS generation_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id           TEXT NOT NULL,
    period_type         TEXT NOT NULL,
    period_label        TEXT NOT NULL,
    generation_gwh      REAL NOT NULL,
    value_type          TEXT NOT NULL DEFAULT 'actual',
    measurement_scope   TEXT NOT NULL DEFAULT 'plant',
    unit_raw            TEXT,
    value_raw           TEXT,
    source_id           TEXT,
    task_id             TEXT,
    -- 升级溯源（文档 15/16.2）：只有 publishable 记录能进 Top100；
    -- evidence_id 保证正式事实与证据不脱钩，validation/review 状态可回溯。
    evidence_id         TEXT,
    confidence          REAL,
    extractor           TEXT,
    validation_status   TEXT,
    review_status       TEXT,
    publication_status  TEXT NOT NULL DEFAULT 'draft',
    created_at          TEXT,
    updated_at          TEXT,
    UNIQUE (entity_id, period_type, period_label, value_type, measurement_scope),
    FOREIGN KEY (source_id) REFERENCES sources(source_id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
CREATE INDEX IF NOT EXISTS idx_gen_entity ON generation_records(entity_id);
CREATE INDEX IF NOT EXISTS idx_gen_period ON generation_records(period_label);

-- 7) 证据表（文档 14：证据必须能回到原始资料/页面/表格位置，且与原始资料不可脱钩）
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id     TEXT PRIMARY KEY,
    source_id       TEXT,
    document_id     TEXT,
    content_hash    TEXT,
    fact_type       TEXT NOT NULL,
    fact_key        TEXT NOT NULL,
    source_url      TEXT,
    final_url       TEXT,
    page_number     INTEGER,
    table_reference TEXT,
    section_title   TEXT,
    snippet         TEXT,
    locator         TEXT,
    confidence      REAL,
    parser_version  TEXT,
    extraction_version TEXT,
    task_id         TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(source_id),
    FOREIGN KEY (document_id) REFERENCES documents(document_id),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_fact ON evidence(fact_type, fact_key);
CREATE INDEX IF NOT EXISTS idx_evidence_doc ON evidence(document_id);

-- 8) 人工复核队列
CREATE TABLE IF NOT EXISTS review_items (
    review_id       TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL,
    fact_type       TEXT NOT NULL,
    fact_key        TEXT NOT NULL,
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',
    payload         TEXT,
    resolved_value  TEXT,
    reviewer        TEXT,
    created_at      TEXT NOT NULL,
    resolved_at     TEXT,
    task_id         TEXT,
    UNIQUE (entity_id, fact_type, fact_key),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status);

-- 9) 任务运行日志（每次尝试一条，用于审计与失败分析）
CREATE TABLE IF NOT EXISTS task_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    attempt         INTEGER NOT NULL,
    status          TEXT NOT NULL,
    failure_stage   TEXT,
    message         TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id);

-- 10) 注册表版本审计（seed 导入批次留痕）
CREATE TABLE IF NOT EXISTS registry_audit (
    audit_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    registry_kind       TEXT NOT NULL,
    registry_version    TEXT,
    row_count           INTEGER NOT NULL,
    source_file         TEXT,
    imported_at         TEXT NOT NULL
);

-- 11) 原始资料归档（文档 10.3）
-- document_id 由 (original_url, content_hash) 派生：同 URL 内容变化 → 新 id、新版本。
-- 原始资料不可覆盖：同一 document_id 幂等，不重复落盘。
CREATE TABLE IF NOT EXISTS documents (
    document_id     TEXT PRIMARY KEY,
    entity_id       TEXT,
    task_id         TEXT,
    source_id       TEXT,
    original_url    TEXT NOT NULL,
    final_url       TEXT,
    fetched_at      TEXT,
    published_at    TEXT,
    content_type    TEXT,
    content_kind    TEXT,
    file_size       INTEGER NOT NULL,
    content_hash    TEXT NOT NULL,
    local_path      TEXT NOT NULL,
    access_method   TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);
CREATE INDEX IF NOT EXISTS idx_documents_url ON documents(original_url);
CREATE INDEX IF NOT EXISTS idx_documents_entity ON documents(entity_id);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);

