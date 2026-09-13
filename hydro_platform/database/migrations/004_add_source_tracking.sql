-- Migration 004: 添加来源跟踪字段到tasks表
-- 用途：D01/D10 - 保证用户指定的来源不被自动搜索替换

-- 添加 source_type 字段：manual（用户指定）/ automatic（自动搜索）
ALTER TABLE tasks ADD COLUMN source_type TEXT DEFAULT 'automatic';

-- 添加 user_specified_source 字段：保存用户原始指定的URL或文件路径
ALTER TABLE tasks ADD COLUMN user_specified_source TEXT;

-- 创建索引加速查询
CREATE INDEX IF NOT EXISTS idx_tasks_source_type ON tasks(source_type);
