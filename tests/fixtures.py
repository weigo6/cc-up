import sqlite3

SCHEMA = """
CREATE TABLE proxy_request_logs (
 request_id TEXT PRIMARY KEY, provider_id TEXT NOT NULL DEFAULT 'provider',
 app_type TEXT NOT NULL DEFAULT 'codex', model TEXT NOT NULL DEFAULT 'model',
 request_model TEXT, pricing_model TEXT,
 input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
 cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
 input_token_semantics INTEGER NOT NULL DEFAULT 0,
 input_cost_usd TEXT DEFAULT '0', output_cost_usd TEXT DEFAULT '0',
 cache_read_cost_usd TEXT DEFAULT '0', cache_creation_cost_usd TEXT DEFAULT '0',
 total_cost_usd TEXT NOT NULL DEFAULT '0', latency_ms INTEGER DEFAULT 0,
 first_token_ms INTEGER, duration_ms INTEGER, status_code INTEGER NOT NULL DEFAULT 200,
 error_message TEXT, session_id TEXT, provider_type TEXT, is_streaming INTEGER DEFAULT 1,
 cost_multiplier TEXT DEFAULT '1', created_at INTEGER NOT NULL,
 data_source TEXT NOT NULL DEFAULT 'proxy'
);
CREATE INDEX idx_time ON proxy_request_logs(created_at);
CREATE INDEX idx_dedup ON proxy_request_logs(app_type,COALESCE(data_source,'proxy'),input_tokens,output_tokens,cache_read_tokens,created_at);
CREATE TABLE usage_daily_rollups (
 date TEXT, app_type TEXT, provider_id TEXT DEFAULT 'provider', model TEXT DEFAULT 'model',
 request_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0, input_tokens INTEGER DEFAULT 0,
 output_tokens INTEGER DEFAULT 0, cache_read_tokens INTEGER DEFAULT 0,
 cache_creation_tokens INTEGER DEFAULT 0, input_token_semantics INTEGER DEFAULT 2,
 total_cost_usd TEXT DEFAULT '0'
);
"""


def database(path):
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.close()


def insert(path, **values):
    connection = sqlite3.connect(path)
    fields = ','.join(values)
    marks = ','.join('?' for _ in values)
    connection.execute(f'INSERT INTO proxy_request_logs({fields}) VALUES({marks})', list(values.values()))
    connection.commit()
    connection.close()
