-- 迁移 v4 → v5: 修复候选/事实分离、外键违规、审批版本
-- 对应审查报告 D06/D07/D08/D14/D15

-- ============================================================
-- 第1步：备份关键数据
-- ============================================================

-- 在Python代码中自动备份数据库文件
-- 此处仅做SQL层面准备

-- ============================================================
-- 第2步：修复外键违规（D14）
-- ============================================================

-- 删除 generation_records 中引用不存在 source_id 的记录
-- 审查报告发现4条测试数据引用 'test-source-001' 但该 source 不存在
DELETE FROM generation_records
WHERE source_id NOT IN (SELECT source_id FROM sources WHERE source_id IS NOT NULL)
  AND source_id IS NOT NULL;

-- 记录违规数量到日志（通过Python实现）

-- ============================================================
-- 第3步：扩展 sources 表（v5新增列）
-- ============================================================

-- 注意：SQLite 不支持 IF NOT EXISTS for ALTER TABLE ADD COLUMN
-- 如果列已存在会报错，但不影响整体迁移（Python代码会处理）

-- 尝试添加新列（可能已存在）
-- ALTER TABLE sources ADD COLUMN entity_type TEXT;
-- ALTER TABLE sources ADD COLUMN canonical_url TEXT;
-- ALTER TABLE sources ADD COLUMN document_type TEXT;
-- ALTER TABLE sources ADD COLUMN covered_metric TEXT;

-- 跳过 ALTER TABLE，因为这些列可能在 v2 已添加
-- 验证函数会检查列是否存在

-- ============================================================
-- 第4步：创建新表
-- ============================================================

-- 不可变候选表
CREATE TABLE IF NOT EXISTS extraction_candidates (
    candidate_id TEXT PRIMARY KEY,
    task_id TEXT,
    entity_id TEXT,
    document_id TEXT NOT NULL,

    -- 候选内容
    period_type TEXT NOT NULL,
    period_label TEXT NOT NULL,
    value_type TEXT NOT NULL,
    measurement_scope TEXT NOT NULL,
    generation_gwh REAL,

    -- 原始信息
    value_raw TEXT,
    unit_raw TEXT,
    snippet TEXT,
    extraction_method TEXT,

    -- 时间戳
    extracted_at TEXT NOT NULL,

    FOREIGN KEY (entity_id) REFERENCES stations(entity_id),
    FOREIGN KEY (document_id) REFERENCES documents(document_id),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

-- 候选证据关联
CREATE TABLE IF NOT EXISTS candidate_evidence (
    candidate_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    PRIMARY KEY (candidate_id, evidence_id),
    FOREIGN KEY (candidate_id) REFERENCES extraction_candidates(candidate_id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
);

-- 复核操作历史
CREATE TABLE IF NOT EXISTS review_events (
    event_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL,
    candidate_id TEXT,

    action TEXT NOT NULL,
    decision TEXT,
    reviewer TEXT,
    reason TEXT,

    created_at TEXT NOT NULL,

    FOREIGN KEY (review_id) REFERENCES review_items(review_id),
    FOREIGN KEY (candidate_id) REFERENCES extraction_candidates(candidate_id)
);

-- 事实变更历史
CREATE TABLE IF NOT EXISTS generation_record_history (
    history_id TEXT PRIMARY KEY,
    record_id INTEGER NOT NULL,

    old_generation_gwh REAL,
    old_candidate_id TEXT,
    old_evidence_id TEXT,
    old_publication_status TEXT,

    new_generation_gwh REAL,
    new_candidate_id TEXT,
    new_evidence_id TEXT,
    new_publication_status TEXT,

    change_type TEXT NOT NULL,
    reason TEXT,
    changed_by TEXT,
    changed_at TEXT NOT NULL,

    FOREIGN KEY (record_id) REFERENCES generation_records(id),
    FOREIGN KEY (old_candidate_id) REFERENCES extraction_candidates(candidate_id),
    FOREIGN KEY (new_candidate_id) REFERENCES extraction_candidates(candidate_id)
);

-- ============================================================
-- 第5步：扩展 generation_records 表
-- ============================================================

-- 添加候选关联列
ALTER TABLE generation_records ADD COLUMN candidate_id TEXT;

-- 创建外键索引（SQLite不支持直接添加外键，通过索引模拟）
CREATE INDEX IF NOT EXISTS idx_generation_candidate ON generation_records(candidate_id);

-- ============================================================
-- 第6步：创建新索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_candidates_entity ON extraction_candidates(entity_id);
CREATE INDEX IF NOT EXISTS idx_candidates_task ON extraction_candidates(task_id);
CREATE INDEX IF NOT EXISTS idx_candidates_document ON extraction_candidates(document_id);

CREATE INDEX IF NOT EXISTS idx_review_events_review ON review_events(review_id);
CREATE INDEX IF NOT EXISTS idx_review_events_candidate ON review_events(candidate_id);

CREATE INDEX IF NOT EXISTS idx_generation_history_record ON generation_record_history(record_id);

-- ============================================================
-- 第7步：更新 v_top100_generation 视图（D04修复）
-- ============================================================

-- 删除旧视图
DROP VIEW IF EXISTS v_top100_generation;

-- 创建严格过滤的新视图
CREATE VIEW v_top100_generation AS
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

-- ============================================================
-- 第8步：迁移现有数据（可选，仅针对已有正式记录）
-- ============================================================

-- 为现有的 generation_records 创建对应的历史记录
-- 标记为初始状态
INSERT INTO generation_record_history (
    history_id,
    record_id,
    new_generation_gwh,
    new_evidence_id,
    new_publication_status,
    change_type,
    reason,
    changed_by,
    changed_at
)
SELECT
    'init_' || id,
    id,
    generation_gwh,
    evidence_id,
    publication_status,
    'created',
    'v4数据迁移',
    'system',
    COALESCE(created_at, datetime('now'))
FROM generation_records
WHERE id NOT IN (SELECT record_id FROM generation_record_history WHERE record_id IS NOT NULL);

-- ============================================================
-- 第9步：完成迁移标记
-- ============================================================

-- 更新 schema_version（通过 Python migrations.py 实现）
-- INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (5, datetime('now'));
