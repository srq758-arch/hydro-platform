-- Migration 001: 扩展 sources 表以支持 SourceRegistry
-- 为历史来源管理、可靠性评分、任务适配性评估添加必要字段

-- 1. 添加实体关联字段
ALTER TABLE sources ADD COLUMN entity_id TEXT;
ALTER TABLE sources ADD COLUMN entity_type TEXT DEFAULT 'station';

-- 2. 添加 URL 字段（为了兼容性保留旧 url 列，添加新的详细字段）
ALTER TABLE sources ADD COLUMN source_url TEXT;
ALTER TABLE sources ADD COLUMN canonical_url TEXT;

-- 3. 添加来源分类字段
ALTER TABLE sources ADD COLUMN source_type TEXT;  -- official/authority/search_result/reference
ALTER TABLE sources ADD COLUMN document_type TEXT;  -- pdf/html/excel/json

-- 4. 添加覆盖范围字段
ALTER TABLE sources ADD COLUMN covered_metric TEXT;  -- generation/capacity
ALTER TABLE sources ADD COLUMN covered_year INTEGER;

-- 5. 添加访问方式
ALTER TABLE sources ADD COLUMN access_method TEXT DEFAULT 'http';  -- http/playwright

-- 6. 添加可靠性评分字段
ALTER TABLE sources ADD COLUMN source_reliability_score REAL DEFAULT 0.5;
ALTER TABLE sources ADD COLUMN task_fit_score REAL;
ALTER TABLE sources ADD COLUMN record_confidence_score REAL;

-- 7. 添加匹配原因
ALTER TABLE sources ADD COLUMN match_reason TEXT;

-- 8. 添加成功/失败统计
ALTER TABLE sources ADD COLUMN success_count INTEGER DEFAULT 0;
ALTER TABLE sources ADD COLUMN failure_count INTEGER DEFAULT 0;
ALTER TABLE sources ADD COLUMN last_success TEXT;
ALTER TABLE sources ADD COLUMN last_failure TEXT;
ALTER TABLE sources ADD COLUMN failure_reason TEXT;

-- 9. 添加时间戳（如果不存在）
ALTER TABLE sources ADD COLUMN created_at TEXT;
ALTER TABLE sources ADD COLUMN updated_at TEXT;

-- 10. 创建新索引以加速 SourceRegistry 查询
CREATE INDEX IF NOT EXISTS idx_sources_entity ON sources(entity_id, covered_metric);
CREATE INDEX IF NOT EXISTS idx_sources_score ON sources(source_reliability_score DESC);
CREATE INDEX IF NOT EXISTS idx_sources_year ON sources(covered_year);
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);

-- 11. 迁移现有数据：将 url 复制到 source_url（如果有数据）
UPDATE sources SET source_url = url WHERE source_url IS NULL AND url IS NOT NULL;
UPDATE sources SET canonical_url = url WHERE canonical_url IS NULL AND url IS NOT NULL;
