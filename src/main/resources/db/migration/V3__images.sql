CREATE TABLE images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER REFERENCES sessions(id),
    device_id     TEXT    NOT NULL,
    filter        TEXT    NOT NULL DEFAULT '',
    target        TEXT    NOT NULL DEFAULT '',
    exposure_s    REAL    NOT NULL DEFAULT 0,
    step_name     TEXT    NOT NULL DEFAULT '',
    seq_index     INTEGER NOT NULL DEFAULT 0,
    fits_path     TEXT    NOT NULL,
    thumb_path    TEXT,
    bytes         INTEGER NOT NULL DEFAULT 0,
    width         INTEGER,
    height        INTEGER,
    bitpix        INTEGER,
    date_obs      TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_images_session_id ON images(session_id);
CREATE INDEX idx_images_created_at ON images(created_at);
CREATE INDEX idx_images_device_id  ON images(device_id);
CREATE INDEX idx_images_target     ON images(target);
