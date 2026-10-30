CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    root_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id),
    adapter_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    control_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    target_episodes INTEGER NOT NULL,
    collector_url TEXT,
    worker_pid INTEGER,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    episode_uuid TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL UNIQUE,
    task TEXT NOT NULL,
    operator_success INTEGER,
    auto_success INTEGER,
    qa_status TEXT NOT NULL DEFAULT 'pending',
    failure_reason TEXT,
    num_frames INTEGER NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exports (
    id TEXT PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id),
    format TEXT NOT NULL,
    status TEXT NOT NULL,
    output_path TEXT NOT NULL,
    error TEXT,
    worker_pid INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_episodes_session_qa ON episodes(session_id, qa_status);
CREATE INDEX IF NOT EXISTS idx_exports_dataset ON exports(dataset_id, created_at);
