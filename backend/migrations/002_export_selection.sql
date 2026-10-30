CREATE TABLE IF NOT EXISTS export_specs (
    export_id TEXT PRIMARY KEY REFERENCES exports(id) ON DELETE CASCADE,
    output_name TEXT NOT NULL,
    repo_id TEXT,
    images INTEGER NOT NULL,
    profile TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_episodes (
    export_id TEXT NOT NULL REFERENCES exports(id) ON DELETE CASCADE,
    episode_id INTEGER NOT NULL REFERENCES episodes(id),
    position INTEGER NOT NULL,
    PRIMARY KEY (export_id, episode_id),
    UNIQUE (export_id, position)
);

CREATE INDEX IF NOT EXISTS idx_export_episodes_episode ON export_episodes(episode_id);
