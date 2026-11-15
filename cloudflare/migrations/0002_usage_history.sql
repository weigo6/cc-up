-- Long-term token history is independent from request-log retention.
CREATE TABLE IF NOT EXISTS usage_daily (
    device_id TEXT NOT NULL,
    day TEXT NOT NULL,
    report_seq INTEGER NOT NULL,
    computed_at INTEGER NOT NULL,
    offset_minutes INTEGER NOT NULL,
    rule_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (device_id, day)
);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_daily(day, device_id);
