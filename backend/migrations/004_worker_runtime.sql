CREATE TABLE IF NOT EXISTS worker_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    engine_id TEXT NOT NULL,
    status TEXT NOT NULL,
    supervisor_pid INTEGER,
    supervisor_boot_id TEXT,
    supervisor_start_ticks INTEGER,
    child_pid INTEGER,
    command_json TEXT NOT NULL,
    cwd TEXT NOT NULL,
    log_path TEXT NOT NULL,
    state_path TEXT NOT NULL,
    readiness_json TEXT NOT NULL,
    ready_at TEXT,
    heartbeat_at TEXT,
    stopped_at TEXT,
    return_code INTEGER,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_worker_runs_session_created
    ON worker_runs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_worker_runs_status
    ON worker_runs(status, updated_at);

CREATE TABLE IF NOT EXISTS worker_resource_locks (
    resource_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES worker_runs(run_id) ON DELETE CASCADE,
    acquired_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_worker_resource_locks_run
    ON worker_resource_locks(run_id);
