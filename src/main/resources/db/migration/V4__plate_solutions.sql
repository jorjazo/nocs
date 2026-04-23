CREATE TABLE plate_solutions (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id                    INTEGER NOT NULL UNIQUE REFERENCES images(id) ON DELETE CASCADE,
    ra_j2000_deg                REAL    NOT NULL,
    dec_j2000_deg               REAL    NOT NULL,
    pixel_scale_arcsec_per_px   REAL    NOT NULL DEFAULT 0,
    rotation_deg                REAL    NOT NULL DEFAULT 0,
    field_width_deg             REAL    NOT NULL DEFAULT 0,
    field_height_deg            REAL    NOT NULL DEFAULT 0,
    duration_ms                 INTEGER NOT NULL DEFAULT 0,
    solver                      TEXT    NOT NULL DEFAULT 'astap',
    solved_at                   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_plate_solutions_image_id ON plate_solutions(image_id);
CREATE INDEX idx_plate_solutions_solved_at ON plate_solutions(solved_at);
