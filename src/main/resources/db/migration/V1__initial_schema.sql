CREATE TABLE config_kv (
    key   TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    opened_at  TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at  TEXT
);

CREATE INDEX idx_sessions_opened_at ON sessions(opened_at);

CREATE TABLE session_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES sessions(id),
    ts           TEXT NOT NULL DEFAULT (datetime('now')),
    topic        TEXT NOT NULL,
    type         TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_session_events_session_id ON session_events(session_id);
CREATE INDEX idx_session_events_ts ON session_events(ts);
