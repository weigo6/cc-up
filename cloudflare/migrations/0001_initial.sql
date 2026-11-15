CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    last_seen INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS request_logs (
    device_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (device_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_logs_time
    ON request_logs(created_at DESC, device_id DESC, request_id DESC);

-- One atomic, complete snapshot per device. Old groups disappear on replacement.
CREATE TABLE IF NOT EXISTS usage_snapshots (
    device_id TEXT PRIMARY KEY,
    report_seq INTEGER NOT NULL,
    computed_at INTEGER NOT NULL,
    offset_minutes INTEGER NOT NULL,
    rule_version TEXT NOT NULL,
    payload TEXT NOT NULL
);
