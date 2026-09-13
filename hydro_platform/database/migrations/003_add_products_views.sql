-- Migration 003: 添加 Products 输出层相关视图和索引
-- 支持 Top 100 计算和项目清单导出（文档 §20）

-- 1. 优化 generation_records 查询索引
CREATE INDEX IF NOT EXISTS idx_gen_top100
ON generation_records(
    publication_status,
    review_status,
    value_type,
    measurement_scope,
    period_label,
    generation_gwh DESC
);

-- 2. 为 projects 表添加状态和年份组合索引
CREATE INDEX IF NOT EXISTS idx_projects_status_year
ON projects(status, commissioning_year);

-- 3. 创建 Top 100 视图（便于快速查询）
CREATE VIEW IF NOT EXISTS v_top100_generation AS
SELECT
    r.entity_id,
    s.canonical_name,
    s.country,
    s.region,
    s.capacity_mw,
    r.period_label AS year,
    r.generation_gwh,
    r.unit_raw,
    r.confidence,
    r.source_id,
    r.evidence_id,
    ROW_NUMBER() OVER (
        PARTITION BY r.period_label
        ORDER BY r.generation_gwh DESC
    ) AS rank
FROM generation_records r
JOIN stations s ON r.entity_id = s.entity_id
WHERE r.publication_status = 'publishable'
  AND r.review_status = 'approved'
  AND r.value_type = 'actual'
  AND r.measurement_scope = 'plant';

-- 4. 创建待复核项统计视图
CREATE VIEW IF NOT EXISTS v_review_queue_stats AS
SELECT
    status,
    fact_type,
    COUNT(*) AS count
FROM review_items
GROUP BY status, fact_type;

-- 5. 创建任务执行统计视图
CREATE VIEW IF NOT EXISTS v_task_stats AS
SELECT
    status,
    failure_stage,
    COUNT(*) AS count,
    AVG(attempts) AS avg_attempts
FROM tasks
GROUP BY status, failure_stage;

-- 6. 创建数据覆盖率统计视图
CREATE VIEW IF NOT EXISTS v_data_coverage AS
SELECT
    s.country,
    r.period_label AS year,
    COUNT(DISTINCT r.entity_id) AS stations_with_data,
    COUNT(DISTINCT s.entity_id) AS total_stations,
    ROUND(
        100.0 * COUNT(DISTINCT r.entity_id) / NULLIF(COUNT(DISTINCT s.entity_id), 0),
        1
    ) AS coverage_percent
FROM stations s
LEFT JOIN generation_records r ON s.entity_id = r.entity_id
    AND r.publication_status = 'publishable'
    AND r.review_status = 'approved'
    AND r.value_type = 'actual'
GROUP BY s.country, r.period_label;
