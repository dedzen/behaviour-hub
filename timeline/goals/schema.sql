PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS goal_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision INTEGER NOT NULL DEFAULT 1,
    schedule TEXT NOT NULL CHECK(schedule IN ('recurring', 'one_off')),
    period TEXT NOT NULL CHECK(period IN ('day', 'week')),
    start_period TEXT NOT NULL,
    end_period_exclusive TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived')),
    created_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS goal_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL,
    effective_from TEXT NOT NULL,
    title TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    rule_config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(series_id) REFERENCES goal_series(id) ON DELETE CASCADE,
    UNIQUE(series_id, effective_from)
);

CREATE INDEX IF NOT EXISTS idx_goal_series_period
ON goal_series(period, start_period, end_period_exclusive);

CREATE INDEX IF NOT EXISTS idx_goal_versions_effective
ON goal_versions(series_id, effective_from);
