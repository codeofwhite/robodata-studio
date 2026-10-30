CREATE TABLE IF NOT EXISTS consumer_smokes (
    id TEXT PRIMARY KEY,
    export_id TEXT NOT NULL UNIQUE REFERENCES exports(id) ON DELETE CASCADE,
    consumer TEXT NOT NULL,
    status TEXT NOT NULL,
    report_path TEXT NOT NULL,
    log_path TEXT NOT NULL,
    error TEXT,
    worker_pid INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_consumer_smokes_status ON consumer_smokes(status, created_at);
