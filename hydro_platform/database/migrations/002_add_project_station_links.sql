-- Migration 002: 添加项目-电站关联表和项目状态历史表
-- 支持 Project-Station Linking 机制（文档 §6.3）

-- 1. 项目-电站关联表
CREATE TABLE IF NOT EXISTS project_station_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    link_type TEXT NOT NULL,  -- commissioning / expansion / upgrade
    effective_date TEXT,
    confidence_score REAL DEFAULT 1.0,
    source_id TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (project_id) REFERENCES projects(entity_id),
    FOREIGN KEY (station_id) REFERENCES stations(entity_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id),

    UNIQUE(project_id, station_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_project_station_links_project
ON project_station_links(project_id);

CREATE INDEX IF NOT EXISTS idx_project_station_links_station
ON project_station_links(station_id);

-- 2. 项目状态变更历史表
CREATE TABLE IF NOT EXISTS project_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- announced / approved / under_construction / newly_commissioned
    effective_date TEXT,
    source_id TEXT,
    notes TEXT,
    recorded_at TEXT NOT NULL,

    FOREIGN KEY (project_id) REFERENCES projects(entity_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE INDEX IF NOT EXISTS idx_project_status_history_project
ON project_status_history(project_id);

CREATE INDEX IF NOT EXISTS idx_project_status_history_status
ON project_status_history(status);

-- 3. 为 projects 表添加额外字段（如果不存在）
-- expected_commissioning_date 和 actual_commissioning_date
-- 使用 ALTER TABLE 兼容已有数据

-- 检查列是否存在的方式：SQLite 不支持 IF NOT EXISTS for columns
-- 但 ALTER TABLE ADD COLUMN 在列已存在时会报错
-- 我们在迁移运行器中处理这个错误

-- 添加预期投产日期
-- ALTER TABLE projects ADD COLUMN expected_commissioning_date TEXT;

-- 添加实际投产日期
-- ALTER TABLE projects ADD COLUMN actual_commissioning_date TEXT;

-- 注意：由于 SQLite 限制，上面两个 ALTER TABLE 需要在 runner 中用 try-except 包装
