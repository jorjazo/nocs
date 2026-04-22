CREATE TABLE observatories (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    latitude_deg      REAL    NOT NULL,
    longitude_deg     REAL    NOT NULL,
    elevation_m       REAL    NOT NULL DEFAULT 0,
    timezone          TEXT    NOT NULL DEFAULT 'UTC',
    horizon_mask_json TEXT    NOT NULL DEFAULT '[]',
    is_active         INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX idx_observatories_single_active
    ON observatories(is_active) WHERE is_active = 1;

CREATE TABLE targets_custom (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    ra_j2000_deg REAL    NOT NULL,
    dec_j2000_deg REAL   NOT NULL,
    kind         TEXT    NOT NULL DEFAULT 'CUSTOM',
    notes        TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_targets_custom_name ON targets_custom(name);
