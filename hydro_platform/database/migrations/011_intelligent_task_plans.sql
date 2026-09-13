-- Migration 011: 自然语言智能任务的规划与审计台账。
-- 这不是采集事实表；任何 LLM 搜索结果必须仍经过候选预检和用户确认。

CREATE TABLE IF NOT EXISTS intelligent_task_plans (
    plan_id             TEXT PRIMARY KEY,
    user_prompt         TEXT NOT NULL,
    entity_id           TEXT,
    target_period       TEXT,
    metric              TEXT,
    source_policy       TEXT NOT NULL DEFAULT 'official_or_authority',
    auto_execute        INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL,
    intent_json         TEXT,
    search_queries_json TEXT,
    candidate_json      TEXT,
    error               TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (entity_id) REFERENCES stations(entity_id)
);

CREATE INDEX IF NOT EXISTS idx_intelligent_task_plans_status
    ON intelligent_task_plans(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_intelligent_task_plans_entity
    ON intelligent_task_plans(entity_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS intelligent_task_events (
    event_id    TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL,
    stage       TEXT NOT NULL,
    message     TEXT NOT NULL,
    payload_json TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES intelligent_task_plans(plan_id)
);

CREATE INDEX IF NOT EXISTS idx_intelligent_task_events_plan
    ON intelligent_task_events(plan_id, created_at);
