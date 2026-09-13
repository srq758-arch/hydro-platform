-- Schema v5: 修复候选/事实分离、外键违规、审批版本问题
-- 对应审查报告 D06/D07/D08/D14/D15

-- ============================================================
-- 核心实体表（保持兼容 v4）
-- ============================================================

CREATE TABLE IF NOT EXISTS stations (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT DEFAULT 'station',
    canonical_name TEXT NOT NULL,
    aliases TEXT,
    local_name TEXT,
    country TEXT,
    country_2 TEXT,
    region TEXT,
    subregion TEXT,
    state_province TEXT,
    river TEXT,
    latitude REAL,
    longitude REAL,
    location_accuracy TEXT,
    capacity_mw REAL,
    turbines INTEGER,
    status TEXT,
    technology TEXT,
    operator TEXT,
    owner TEXT,
    commissioning_year INTEGER,
    retired_year INTEGER,
    gem_location_id TEXT,
    gem_unit_id TEXT,
    gem_wiki_url TEXT,
    priority_tier TEXT,
    collection_priority INTEGER,
    needs_review INTEGER DEFAULT 0,
    source_seed TEXT,
    source_url TEXT,
    dataset_version TEXT,
    registry_version TEXT,
    raw_record_hash TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT DEFAULT 'project',
    canonical_name TEXT NOT NULL,
    aliases TEXT,
    local_name TEXT,
    country TEXT,
    country_2 TEXT,
    region TEXT,
    subregion TEXT,
    state_province TEXT,
    river TEXT,
    latitude REAL,
    longitude REAL,
    location_accuracy TEXT,
    capacity_mw REAL,
    turbines INTEGER,
    status TEXT,
    technology TEXT,
    operator TEXT,
    owner TEXT,
    commissioning_year INTEGER,
    gem_location_id TEXT,
    gem_unit_id TEXT,
    gem_wiki_url TEXT,
    priority_tier TEXT,
    collection_priority INTEGER,
    needs_review INTEGER DEFAULT 0,
    source_seed TEXT,
    source_url TEXT,
    dataset_version TEXT,
    registry_version TEXT,
    raw_record_hash TEXT
);

CREATE TABLE IF NOT EXISTS project_station_links (
    link_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    link_date TEXT,
    confidence REAL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(entity_id),
    FOREIGN KEY (station_id) REFERENCES stations(entity_id)
);

CREATE TABLE IF NOT EXISTS project_status_history (
    history_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL,
    status_date TEXT,
    confidence REAL,
    source_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(entity_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

-- ============================================================
-- 来源与文档表（v5 增强）
-- ============================================================

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    url TEXT,
    title TEXT,
    publisher TEXT,
    publish_date TEXT,
    retrieved_at TEXT,
    content_hash TEXT,
    archive_path TEXT,
    language TEXT DEFAULT 'en',
    source_tier TEXT,
    reliability_score REAL,
    created_at TEXT,
    updated_at TEXT,
    -- v5 新增
    entity_type TEXT,  -- 来源涉及的实体类型
    canonical_url TEXT,  -- 规范化URL
    document_type TEXT,  -- 文档类型分类
    covered_metric TEXT,  -- 覆盖的指标
    UNIQUE(url, content_hash)
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    local_path TEXT NOT NULL,
    content_type TEXT,
    content_kind TEXT,
    access_method TEXT,
    archived_at TEXT NOT NULL,
    file_size INTEGER,
    page_count INTEGER,
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

-- ============================================================
-- v5 新增：不可变候选表（D06/D07修复）
-- ============================================================

CREATE TABLE IF NOT EXISTS extraction_candidates (
    candidate_id TEXT PRIMARY KEY,  -- 唯一标识，不可变
    task_id TEXT,
    entity_id TEXT,
    document_id TEXT NOT NULL,

    -- 候选内容（不可变）
    period_type TEXT NOT NULL,
    period_label TEXT NOT NULL,
    value_type TEXT NOT NULL,
    measurement_scope TEXT NOT NULL,
    generation_gwh REAL,

    -- 原始抽取信息
    value_raw TEXT,
    unit_raw TEXT,
    snippet TEXT,
    extraction_method TEXT,  -- 'rule' | 'llm'

    -- 时间戳
    extracted_at TEXT NOT NULL,

    FOREIGN KEY (entity_id) REFERENCES stations(entity_id),
    FOREIGN KEY (document_id) REFERENCES documents(document_id),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

-- 候选证据关联（多对多，支持同一候选有多份证据）
CREATE TABLE IF NOT EXISTS candidate_evidence (
    candidate_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    PRIMARY KEY (candidate_id, evidence_id),
    FOREIGN KEY (candidate_id) REFERENCES extraction_candidates(candidate_id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
);

-- ============================================================
-- 证据表（保持兼容）
-- ============================================================

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    snippet TEXT NOT NULL,
    page_number INTEGER,
    table_reference TEXT,
    locator TEXT,
    confidence REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(document_id)
);

-- ============================================================
-- 复核表（v5 增强）
-- ============================================================

CREATE TABLE IF NOT EXISTS review_items (
    review_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    fact_type TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    task_id TEXT,

    -- 复核状态
    status TEXT NOT NULL DEFAULT 'open',
    reason TEXT,
    payload TEXT,

    -- 审批信息
    reviewer TEXT,
    resolved_value TEXT,
    resolved_at TEXT,

    -- 时间戳
    created_at TEXT NOT NULL,
    updated_at TEXT,

    UNIQUE(entity_id, fact_type, fact_key)
);

-- v5 新增：复核操作历史（D07/D08修复）
CREATE TABLE IF NOT EXISTS review_events (
    event_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL,
    candidate_id TEXT,  -- 关联的候选版本

    -- 操作信息
    action TEXT NOT NULL,  -- 'submit' | 'approve' | 'reject' | 'request_more_evidence' | 'reopen'
    decision TEXT,  -- 决策结果
    reviewer TEXT,
    reason TEXT,

    -- 时间戳
    created_at TEXT NOT NULL,

    FOREIGN KEY (review_id) REFERENCES review_items(review_id),
    FOREIGN KEY (candidate_id) REFERENCES extraction_candidates(candidate_id)
);

-- ============================================================
-- 正式事实表（generation_records）
-- ============================================================

CREATE TABLE IF NOT EXISTS generation_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,

    -- 事实内容
    period_type TEXT NOT NULL,
    period_label TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'actual',
    measurement_scope TEXT NOT NULL DEFAULT 'plant',
    generation_gwh REAL NOT NULL,

    -- 来源与证据
    source_id TEXT,
    evidence_id TEXT,
    candidate_id TEXT,  -- v5 新增：关联的候选版本

    -- 状态
    publication_status TEXT NOT NULL DEFAULT 'draft',
    validation_status TEXT,
    review_status TEXT,
    confidence REAL,

    -- 时间戳
    created_at TEXT NOT NULL,
    updated_at TEXT,

    FOREIGN KEY (entity_id) REFERENCES stations(entity_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id),
    FOREIGN KEY (candidate_id) REFERENCES extraction_candidates(candidate_id),

    UNIQUE(entity_id, period_type, period_label, value_type, measurement_scope)
);

-- v5 新增：事实变更历史（D06修复）
CREATE TABLE IF NOT EXISTS generation_record_history (
    history_id TEXT PRIMARY KEY,
    record_id INTEGER NOT NULL,

    -- 变更前的值
    old_generation_gwh REAL,
    old_candidate_id TEXT,
    old_evidence_id TEXT,
    old_publication_status TEXT,

    -- 变更后的值
    new_generation_gwh REAL,
    new_candidate_id TEXT,
    new_evidence_id TEXT,
    new_publication_status TEXT,

    -- 变更信息
    change_type TEXT NOT NULL,  -- 'created' | 'updated' | 'promoted' | 'rejected'
    reason TEXT,
    changed_by TEXT,
    changed_at TEXT NOT NULL,

    FOREIGN KEY (record_id) REFERENCES generation_records(id),
    FOREIGN KEY (old_candidate_id) REFERENCES extraction_candidates(candidate_id),
    FOREIGN KEY (new_candidate_id) REFERENCES extraction_candidates(candidate_id)
);

-- ============================================================
-- 任务表（保持兼容）
-- ============================================================

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    task_type TEXT NOT NULL,
    target_period TEXT,

    status TEXT NOT NULL DEFAULT 'pending',
    failure_stage TEXT,
    last_error TEXT,
    attempts INTEGER DEFAULT 0,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS task_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,

    status TEXT NOT NULL DEFAULT 'running',
    failure_stage TEXT,
    message TEXT,

    started_at TEXT NOT NULL,
    finished_at TEXT,

    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

-- ============================================================
-- 索引（性能优化）
-- ============================================================

-- 实体查询
CREATE INDEX IF NOT EXISTS idx_stations_country ON stations(country);
CREATE INDEX IF NOT EXISTS idx_stations_priority ON stations(priority_tier);
CREATE INDEX IF NOT EXISTS idx_projects_country ON projects(country);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

-- 来源查询
CREATE INDEX IF NOT EXISTS idx_sources_publisher ON sources(publisher);
CREATE INDEX IF NOT EXISTS idx_sources_tier ON sources(source_tier);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id);

-- 候选查询
CREATE INDEX IF NOT EXISTS idx_candidates_entity ON extraction_candidates(entity_id);
CREATE INDEX IF NOT EXISTS idx_candidates_task ON extraction_candidates(task_id);
CREATE INDEX IF NOT EXISTS idx_candidates_document ON extraction_candidates(document_id);

-- 复核查询
CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status);
CREATE INDEX IF NOT EXISTS idx_review_entity ON review_items(entity_id);
CREATE INDEX IF NOT EXISTS idx_review_events_review ON review_events(review_id);
CREATE INDEX IF NOT EXISTS idx_review_events_candidate ON review_events(candidate_id);

-- 事实查询
CREATE INDEX IF NOT EXISTS idx_generation_entity ON generation_records(entity_id);
CREATE INDEX IF NOT EXISTS idx_generation_period ON generation_records(period_label);
CREATE INDEX IF NOT EXISTS idx_generation_status ON generation_records(publication_status);
CREATE INDEX IF NOT EXISTS idx_generation_candidate ON generation_records(candidate_id);
CREATE INDEX IF NOT EXISTS idx_generation_history_record ON generation_record_history(record_id);

-- 任务查询
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_entity ON tasks(entity_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id);

-- ============================================================
-- 视图（兼容性）
-- ============================================================

-- Top 100 可信事实视图（严格过滤）
CREATE VIEW IF NOT EXISTS v_top100_generation AS
SELECT
    g.id,
    g.entity_id,
    s.canonical_name,
    s.country,
    g.period_label,
    g.generation_gwh,
    g.confidence,
    g.source_id,
    src.title AS source_title,
    g.created_at
FROM generation_records g
JOIN stations s ON g.entity_id = s.entity_id
LEFT JOIN sources src ON g.source_id = src.source_id
WHERE g.publication_status = 'publishable'
  AND g.validation_status = 'passed'
  AND g.review_status IN ('approved', 'not_required')
  AND g.period_type = 'calendar_year'
  AND g.value_type = 'actual'
  AND g.measurement_scope = 'plant'
  AND g.evidence_id IS NOT NULL
ORDER BY g.generation_gwh DESC;

-- 数据覆盖统计视图
CREATE VIEW IF NOT EXISTS v_data_coverage AS
SELECT
    s.country,
    g.period_label AS year,
    COUNT(DISTINCT g.entity_id) AS station_count,
    SUM(g.generation_gwh) AS total_generation_gwh
FROM generation_records g
JOIN stations s ON g.entity_id = s.entity_id
WHERE g.publication_status = 'publishable'
  AND g.period_type = 'calendar_year'
  AND g.value_type = 'actual'
GROUP BY s.country, g.period_label;
