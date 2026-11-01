"""The SQLite catalog of saved frames: volumes, targets, nights and frames (ADR 0013).

It also keeps what the night was like for the frames: temperatures sampled from
the focuser and the weather sensor, and autofocus runs (ADR 0021).

One connection, used from worker threads one at a time (every method blocks).
The schema version lives in ``PRAGMA user_version``; ``MIGRATIONS[n]`` takes a
database from version ``n`` to ``n + 1``.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

log = logging.getLogger(__name__)

MIGRATIONS: list[str] = [
    """
    CREATE TABLE volumes (
        id INTEGER PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,          -- filesystem UUID, or mount:<mount point>
        label TEXT NOT NULL,
        mount_point TEXT NOT NULL,         -- where it was last seen
        last_seen TEXT NOT NULL
    );
    CREATE TABLE targets (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE
    );
    CREATE TABLE nights (
        id INTEGER PRIMARY KEY,
        night TEXT NOT NULL UNIQUE,        -- YYYY-MM-DD, the date at the start of the night
        site TEXT,
        first_frame TEXT NOT NULL,
        last_frame TEXT NOT NULL
    );
    CREATE TABLE frames (
        id INTEGER PRIMARY KEY AUTOINCREMENT,  -- ids are never reused (clients keep them)
        night_id INTEGER NOT NULL REFERENCES nights (id),
        target_id INTEGER REFERENCES targets (id),
        volume_id INTEGER NOT NULL REFERENCES volumes (id),
        directory TEXT NOT NULL,           -- destination, relative to the filesystem root
        path TEXT NOT NULL,                -- below <directory>/NOCS/
        size INTEGER NOT NULL,
        started TEXT NOT NULL,             -- exposure start, UTC ISO 8601
        exposure REAL NOT NULL,
        frame_type TEXT NOT NULL,
        filter TEXT,
        profile TEXT,
        camera TEXT NOT NULL,
        gain REAL,
        "offset" REAL,
        binning INTEGER,
        temperature REAL,
        width INTEGER,
        height INTEGER,
        stars INTEGER,
        hfr REAL,
        UNIQUE (volume_id, directory, path)
    );
    CREATE INDEX frames_by_night ON frames (night_id, id);
    """,
    """
    CREATE TABLE temperatures (
        time TEXT NOT NULL PRIMARY KEY,    -- UTC ISO 8601
        focuser REAL,                      -- the focuser's probe, °C
        ambient REAL,                      -- the weather role's, °C
        humidity REAL,                     -- %
        dew_point REAL                     -- °C
    ) WITHOUT ROWID;
    CREATE TABLE focus_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started TEXT NOT NULL,             -- UTC ISO 8601
        finished TEXT NOT NULL,
        profile TEXT,
        filter TEXT,
        state TEXT NOT NULL,               -- succeeded, failed, cancelled
        problem TEXT,
        start_position INTEGER NOT NULL,
        position INTEGER,                  -- best focus, when the run found it
        start_hfr REAL,
        hfr REAL,
        focuser_temperature REAL,
        ambient_temperature REAL,
        run TEXT NOT NULL                  -- the whole run as the state showed it (JSON)
    );
    CREATE INDEX focus_runs_by_time ON focus_runs (started);
    """,
    """
    -- How guiding went during each frame (phase 4.5, ADR 0024).
    ALTER TABLE frames ADD COLUMN guide_rms_ra REAL;     -- arcseconds
    ALTER TABLE frames ADD COLUMN guide_rms_dec REAL;
    ALTER TABLE frames ADD COLUMN guide_rms_total REAL;
    ALTER TABLE frames ADD COLUMN guide_steps INTEGER;
    ALTER TABLE frames ADD COLUMN guide_lost INTEGER;    -- frames without the guide star
    """,
    """
    -- Sequence runs and their events, for the session report (phase 5.12, ADR 0032).
    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run TEXT NOT NULL UNIQUE,          -- the run's id, the same across restarts of nocsd
        sequence TEXT NOT NULL,            -- the sequence's id
        name TEXT NOT NULL,
        profile TEXT,
        started TEXT NOT NULL,             -- UTC ISO 8601
        ended TEXT,
        outcome TEXT,                      -- completed, stopped, failed; NULL until it ends
        error TEXT,
        restarts INTEGER NOT NULL DEFAULT 0,
        definition TEXT NOT NULL           -- the sequence as it ran (JSON)
    );
    CREATE TABLE session_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions (id),
        time TEXT NOT NULL,                -- UTC ISO 8601
        kind TEXT NOT NULL,
        message TEXT NOT NULL,
        path TEXT,                         -- where in the sequence's tree
        data TEXT NOT NULL                 -- JSON: a frame's id, stars and HFR; a failure's kind…
    );
    CREATE INDEX session_events_by_session ON session_events (session_id, id);
    """,
    """
    -- Plate solutions of saved lights, for the framing chart's background (phase 3.7c).
    -- A failed attempt is kept too (ra NULL, failure set), so it is not tried again.
    CREATE TABLE solutions (
        frame_id INTEGER PRIMARY KEY REFERENCES frames (id) ON DELETE CASCADE,
        solved TEXT NOT NULL,              -- when, UTC ISO 8601
        ra REAL,                           -- J2000 centre of the frame, hours
        dec REAL,                          -- degrees
        scale REAL,                        -- arcseconds per pixel
        rotation REAL,                     -- of the top of the image as shown, ° east of north
        mirrored INTEGER,
        width INTEGER,                     -- pixels
        height INTEGER,
        failure TEXT
    );
    CREATE INDEX solutions_by_dec ON solutions (dec);
    """,
    """
    -- What calibration frames are matched by (ADR 0036).
    ALTER TABLE frames ADD COLUMN focus_position INTEGER;  -- FOCUSPOS, steps
    ALTER TABLE frames ADD COLUMN rotation REAL;     -- °, from the night's latest plate solve
    ALTER TABLE frames ADD COLUMN level REAL;        -- a flat's median, ADU (strongest channel)
    CREATE INDEX frames_by_type ON frames (frame_type, camera);
    """,
]
VERSION = len(MIGRATIONS)


class CatalogError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class NewFrame:
    night: date
    site: str | None
    target: str | None
    volume: str
    volume_label: str
    mount_point: str
    directory: PurePosixPath
    path: PurePosixPath
    size: int
    started: datetime
    exposure: float
    frame_type: str
    filter: str | None
    profile: str | None
    camera: str
    gain: float | None
    offset: float | None
    binning: int | None
    temperature: float | None
    width: int | None
    height: int | None
    focus_position: int | None = None
    rotation: float | None = None


@dataclass(frozen=True, slots=True)
class FrameRow:
    id: int
    night: str
    target: str | None
    volume: str
    volume_label: str
    directory: PurePosixPath
    path: PurePosixPath
    size: int
    started: str
    exposure: float
    frame_type: str
    filter: str | None
    profile: str | None
    camera: str
    gain: float | None
    offset: float | None
    binning: int | None
    temperature: float | None
    width: int | None
    height: int | None
    stars: int | None
    hfr: float | None
    guide_rms_ra: float | None = None
    guide_rms_dec: float | None = None
    guide_rms_total: float | None = None
    guide_steps: int | None = None
    guide_lost: int | None = None
    focus_position: int | None = None
    rotation: float | None = None
    level: float | None = None


@dataclass(frozen=True, slots=True)
class NightGroup:
    frame_type: str
    target: str | None
    filter: str | None
    frames: int
    size: int
    exposure: float


@dataclass(frozen=True, slots=True)
class NightRow:
    id: int
    night: str
    site: str | None
    first_frame: str
    last_frame: str
    groups: list[NightGroup]


@dataclass(frozen=True, slots=True)
class TemperatureSample:
    time: str
    """UTC, ISO 8601."""
    focuser: float | None
    ambient: float | None
    humidity: float | None
    dew_point: float | None


@dataclass(frozen=True, slots=True)
class FocusRun:
    started: str
    finished: str
    profile: str | None
    filter: str | None
    state: str
    problem: str | None
    start_position: int
    position: int | None
    start_hfr: float | None
    hfr: float | None
    focuser_temperature: float | None
    ambient_temperature: float | None
    run: str
    """The run as the state showed it, as JSON."""
    id: int | None = None


@dataclass(frozen=True, slots=True)
class FrameFilter:
    night: int | None = None
    target: str | None = None
    frame_type: str | None = None
    filter: str | None = None
    before: int | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class FrameSolution:
    """Where a saved frame points, as ``nocs.solving.Solution`` gives it."""

    ra: float
    """J2000 centre, hours."""
    dec: float
    scale: float
    """Arcseconds per pixel."""
    rotation: float
    """Position angle of the top of the image as NOCS shows it, degrees east of north."""
    mirrored: bool
    width: int
    height: int
    solved: str = ""
    """UTC, ISO 8601."""

    @property
    def fov(self) -> tuple[float, float]:
        """Degrees across x and y."""
        return self.width * self.scale / 3600, self.height * self.scale / 3600


@dataclass(frozen=True, slots=True)
class Session:
    run: str
    sequence: str
    name: str
    profile: str | None
    started: str
    ended: str | None
    outcome: str | None
    error: str | None
    restarts: int
    definition: str
    """The sequence as it ran, as JSON."""
    id: int | None = None


@dataclass(frozen=True, slots=True)
class SessionEvent:
    time: str
    kind: str
    message: str
    path: str | None
    data: str
    """JSON."""


_SESSION_COLUMNS = (
    "run, sequence, name, profile, started, ended, outcome, error, restarts, definition"
)
_RUN_COLUMNS = (
    "started, finished, profile, filter, state, problem, start_position, position,"
    " start_hfr, hfr, focuser_temperature, ambient_temperature, run"
)

_FRAME_COLUMNS = """
    f.id, n.night, t.name, v.key, v.label, f.directory, f.path, f.size, f.started,
    f.exposure, f.frame_type, f.filter, f.profile, f.camera, f.gain, f."offset", f.binning,
    f.temperature, f.width, f.height, f.stars, f.hfr,
    f.guide_rms_ra, f.guide_rms_dec, f.guide_rms_total, f.guide_steps, f.guide_lost,
    f.focus_position, f.rotation, f.level
"""
_FRAME_JOINS = """
    FROM frames f
    JOIN nights n ON n.id = f.night_id
    JOIN volumes v ON v.id = f.volume_id
    LEFT JOIN targets t ON t.id = f.target_id
"""


_SOLUTION_COLUMNS = "s.ra, s.dec, s.scale, s.rotation, s.mirrored, s.width, s.height, s.solved"


def _solution(row: Sequence[Any]) -> FrameSolution:
    ra, dec, scale, rotation, mirrored, width, height, solved = row
    return FrameSolution(
        float(ra),
        float(dec),
        float(scale),
        float(rotation),
        bool(mirrored),
        int(width),
        int(height),
        str(solved),
    )


def _separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Degrees between two J2000 points (hours, degrees)."""
    d1, d2 = math.radians(dec1), math.radians(dec2)
    dra = math.radians((ra2 - ra1) * 15)
    h = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin(dra / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h))))


def _frame(row: Sequence[Any]) -> FrameRow:
    values = list(row)
    values[5] = PurePosixPath(values[5])
    values[6] = PurePosixPath(values[6])
    return FrameRow(*values)


class Catalog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        # Transactions are explicit (BEGIN … COMMIT); autocommit otherwise.
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.execute("PRAGMA synchronous = NORMAL")
            self._db.execute("PRAGMA foreign_keys = ON")
            self._migrate()
        except BaseException:
            self._db.close()
            raise

    @property
    def version(self) -> int:
        version: int = self._db.execute("PRAGMA user_version").fetchone()[0]
        return version

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _migrate(self) -> None:
        current = self.version
        if current > VERSION:
            raise CatalogError(
                f"the catalog {self._path} has schema version {current}, newer than this "
                f"nocsd understands ({VERSION}); it was left untouched"
            )
        if current == VERSION:
            return
        if current > 0:
            backup = self._path.with_name(f"{self._path.name}.v{current}.bak")
            log.info("backing up the catalog to %s before migrating", backup)
            target = sqlite3.connect(backup)
            try:
                self._db.backup(target)
            finally:
                target.close()
        for version in range(current, VERSION):
            log.info("migrating the catalog to schema version %d", version + 1)
            # DDL is transactional in SQLite: a failed step leaves the previous version.
            self._db.executescript(
                f"BEGIN;\n{MIGRATIONS[version]}\nPRAGMA user_version = {version + 1};\nCOMMIT;"
            )

    # -- writing ----------------------------------------------------------

    def target(self, name: str) -> str:
        """The known spelling of a target name (matched ignoring case), adding it if new."""
        with self._lock:
            row = self._db.execute("SELECT name FROM targets WHERE name = ?", (name,)).fetchone()
            if row is not None:
                known: str = row[0]
                return known
            self._db.execute("INSERT INTO targets (name) VALUES (?)", (name,))
            return name

    def add_frame(self, frame: NewFrame) -> int:
        started = frame.started.isoformat(timespec="milliseconds")
        night = frame.night.isoformat()
        with self._lock:
            db = self._db
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    "INSERT INTO volumes (key, label, mount_point, last_seen) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (key) DO UPDATE SET label = excluded.label,"
                    " mount_point = excluded.mount_point, last_seen = excluded.last_seen",
                    (frame.volume, frame.volume_label, frame.mount_point, started),
                )
                volume_id: int = db.execute(
                    "SELECT id FROM volumes WHERE key = ?", (frame.volume,)
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO nights (night, site, first_frame, last_frame) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (night) DO UPDATE SET"
                    " site = coalesce(nights.site, excluded.site),"
                    " first_frame = min(nights.first_frame, excluded.first_frame),"
                    " last_frame = max(nights.last_frame, excluded.last_frame)",
                    (night, frame.site, started, started),
                )
                night_id: int = db.execute(
                    "SELECT id FROM nights WHERE night = ?", (night,)
                ).fetchone()[0]
                target_id: int | None = None
                if frame.target is not None:
                    db.execute(
                        "INSERT INTO targets (name) VALUES (?) ON CONFLICT DO NOTHING",
                        (frame.target,),
                    )
                    target_id = db.execute(
                        "SELECT id FROM targets WHERE name = ?", (frame.target,)
                    ).fetchone()[0]
                # A file deleted outside NOCS may have left a row for the same name.
                db.execute(
                    "DELETE FROM frames WHERE volume_id = ? AND directory = ? AND path = ?",
                    (volume_id, str(frame.directory), str(frame.path)),
                )
                cursor = db.execute(
                    "INSERT INTO frames (night_id, target_id, volume_id, directory, path, size,"
                    ' started, exposure, frame_type, filter, profile, camera, gain, "offset",'
                    " binning, temperature, width, height, focus_position, rotation)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        night_id,
                        target_id,
                        volume_id,
                        str(frame.directory),
                        str(frame.path),
                        frame.size,
                        started,
                        frame.exposure,
                        frame.frame_type,
                        frame.filter,
                        frame.profile,
                        frame.camera,
                        frame.gain,
                        frame.offset,
                        frame.binning,
                        frame.temperature,
                        frame.width,
                        frame.height,
                        frame.focus_position,
                        frame.rotation,
                    ),
                )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        frame_id = cursor.lastrowid
        assert frame_id is not None
        return frame_id

    def set_metrics(self, frame_id: int, stars: int | None, hfr: float | None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE frames SET stars = ?, hfr = ? WHERE id = ?", (stars, hfr, frame_id)
            )

    def set_level(self, frame_id: int, level: float | None) -> None:
        with self._lock:
            self._db.execute("UPDATE frames SET level = ? WHERE id = ?", (level, frame_id))

    def set_guiding(self, frame_id: int, guiding: Mapping[str, object]) -> None:
        """How guiding went during the frame: RMS in arcseconds, steps, lost frames."""

        def value(key: str) -> float | int | None:
            item = guiding.get(key)
            return item if isinstance(item, int | float) and not isinstance(item, bool) else None

        with self._lock:
            self._db.execute(
                "UPDATE frames SET guide_rms_ra = ?, guide_rms_dec = ?, guide_rms_total = ?,"
                " guide_steps = ?, guide_lost = ? WHERE id = ?",
                (
                    value("rms_ra"),
                    value("rms_dec"),
                    value("rms_total"),
                    value("steps"),
                    value("lost"),
                    frame_id,
                ),
            )

    def set_solution(self, frame_id: int, solution: FrameSolution | str) -> None:
        """A frame's solution, or why it could not be solved (a message)."""
        solved = solution.solved if isinstance(solution, FrameSolution) else ""
        solved = solved or datetime.now(UTC).isoformat(timespec="seconds")
        if isinstance(solution, str):
            values = (None,) * 7 + (solution,)
        else:
            values = (
                solution.ra,
                solution.dec,
                solution.scale,
                solution.rotation,
                int(solution.mirrored),
                solution.width,
                solution.height,
                None,
            )
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO solutions (frame_id, solved, ra, dec, scale, rotation,"
                " mirrored, width, height, failure) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (frame_id, solved, *values),
            )

    def add_temperature(self, sample: TemperatureSample) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO temperatures VALUES (?, ?, ?, ?, ?)",
                (sample.time, sample.focuser, sample.ambient, sample.humidity, sample.dew_point),
            )

    def add_focus_run(self, run: FocusRun) -> int:
        with self._lock:
            cursor = self._db.execute(
                f"INSERT INTO focus_runs ({_RUN_COLUMNS}) VALUES ({', '.join('?' * 13)})",
                (
                    run.started,
                    run.finished,
                    run.profile,
                    run.filter,
                    run.state,
                    run.problem,
                    run.start_position,
                    run.position,
                    run.start_hfr,
                    run.hfr,
                    run.focuser_temperature,
                    run.ambient_temperature,
                    run.run,
                ),
            )
        run_id = cursor.lastrowid
        assert run_id is not None
        return run_id

    # -- reading ----------------------------------------------------------

    def temperatures(self, since: str, until: str | None = None) -> list[TemperatureSample]:
        """Samples from ``since`` (inclusive) to ``until`` (exclusive), oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT time, focuser, ambient, humidity, dew_point FROM temperatures"
                " WHERE time >= ? AND (? IS NULL OR time < ?) ORDER BY time",
                (since, until, until),
            ).fetchall()
        return [TemperatureSample(*tuple(row)) for row in rows]

    def start_session(self, session: Session) -> int:
        """Record a run as it starts, or again after a restart (same ``run``); its id."""
        with self._lock:
            self._db.execute(
                f"INSERT INTO sessions ({_SESSION_COLUMNS}) VALUES ({', '.join('?' * 10)})"
                " ON CONFLICT (run) DO UPDATE SET restarts = excluded.restarts",
                (
                    session.run,
                    session.sequence,
                    session.name,
                    session.profile,
                    session.started,
                    session.ended,
                    session.outcome,
                    session.error,
                    session.restarts,
                    session.definition,
                ),
            )
            row = self._db.execute(
                "SELECT id FROM sessions WHERE run = ?", (session.run,)
            ).fetchone()
        session_id: int = row[0]
        return session_id

    def end_session(self, session_id: int, ended: str, outcome: str, error: str | None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE sessions SET ended = ?, outcome = ?, error = ? WHERE id = ?",
                (ended, outcome, error, session_id),
            )

    def add_session_events(self, session_id: int, events: list[SessionEvent]) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT INTO session_events (session_id, time, kind, message, path, data)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [(session_id, e.time, e.kind, e.message, e.path, e.data) for e in events],
            )

    def sessions(self, limit: int = 20, before: int | None = None) -> list[Session]:
        """Newest first."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_SESSION_COLUMNS}, id FROM sessions WHERE (? IS NULL OR id < ?)"
                " ORDER BY id DESC LIMIT ?",
                (before, before, limit),
            ).fetchall()
        return [Session(*tuple(row)) for row in rows]

    def session(self, session_id: int) -> Session | None:
        with self._lock:
            row = self._db.execute(
                f"SELECT {_SESSION_COLUMNS}, id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return Session(*tuple(row)) if row is not None else None

    def session_events(self, session_id: int) -> list[SessionEvent]:
        """Oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT time, kind, message, path, data FROM session_events"
                " WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [SessionEvent(*tuple(row)) for row in rows]

    def focus_runs(self, limit: int = 20, before: int | None = None) -> list[FocusRun]:
        """Newest first."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_RUN_COLUMNS}, id FROM focus_runs WHERE (? IS NULL OR id < ?)"
                " ORDER BY id DESC LIMIT ?",
                (before, before, limit),
            ).fetchall()
        return [FocusRun(*tuple(row)) for row in rows]

    def frame(self, frame_id: int) -> FrameRow | None:
        with self._lock:
            row = self._db.execute(
                f"SELECT {_FRAME_COLUMNS} {_FRAME_JOINS} WHERE f.id = ?", (frame_id,)
            ).fetchone()
        return _frame(row) if row is not None else None

    def frames_by_id(self, frame_ids: list[int]) -> list[FrameRow]:
        """These frames, oldest first; ids not in the catalog are left out."""
        found: list[FrameRow] = []
        with self._lock:
            for start in range(0, len(frame_ids), 500):
                chunk = frame_ids[start : start + 500]
                marks = ",".join("?" * len(chunk))
                rows = self._db.execute(
                    f"SELECT {_FRAME_COLUMNS} {_FRAME_JOINS} WHERE f.id IN ({marks})", chunk
                ).fetchall()
                found.extend(_frame(row) for row in rows)
        return sorted(found, key=lambda frame: frame.id)

    def frames(self, query: FrameFilter) -> list[FrameRow]:
        """Newest first."""
        conditions: list[str] = []
        args: list[object] = []
        for condition, value in (
            ("f.night_id = ?", query.night),
            ("t.name = ?", query.target),
            ("f.frame_type = ?", query.frame_type),
            ("f.filter = ?", query.filter),
            ("f.id < ?", query.before),
        ):
            if value is not None:
                conditions.append(condition)
                args.append(value)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit = ""
        if query.limit is not None:
            limit = "LIMIT ?"
            args.append(query.limit)
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_FRAME_COLUMNS} {_FRAME_JOINS} {where} ORDER BY f.id DESC {limit}", args
            ).fetchall()
        return [_frame(row) for row in rows]

    def calibration_frames(self, cameras: list[str]) -> list[FrameRow]:
        """Every dark, bias and flat of these cameras, newest first."""
        if not cameras:
            return []
        marks = ",".join("?" * len(cameras))
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_FRAME_COLUMNS} {_FRAME_JOINS}"
                f" WHERE f.frame_type IN ('dark', 'bias', 'flat') AND f.camera IN ({marks})"
                " ORDER BY f.id DESC",
                cameras,
            ).fetchall()
        return [_frame(row) for row in rows]

    def solution(self, frame_id: int) -> FrameSolution | None:
        """A frame's solution; ``None`` if it was never solved or failed to."""
        with self._lock:
            row = self._db.execute(
                f"SELECT {_SOLUTION_COLUMNS} FROM solutions s"
                " WHERE frame_id = ? AND ra IS NOT NULL",
                (frame_id,),
            ).fetchone()
        return _solution(row) if row is not None else None

    def solved_near(
        self, ra: float, dec: float, radius: float, limit: int = 20
    ) -> list[tuple[FrameRow, FrameSolution]]:
        """Solved frames whose centre is within ``radius`` degrees of a J2000 point
        (hours, degrees), newest first."""
        low, high = max(-90.0, dec - radius), min(90.0, dec + radius)
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_FRAME_COLUMNS}, {_SOLUTION_COLUMNS} {_FRAME_JOINS}"
                " JOIN solutions s ON s.frame_id = f.id"
                " WHERE s.ra IS NOT NULL AND s.dec BETWEEN ? AND ? ORDER BY f.started DESC",
                (low, high),
            ).fetchall()
        found: list[tuple[FrameRow, FrameSolution]] = []
        frame_columns = len(fields(FrameRow))
        for row in rows:
            solution = _solution(tuple(row)[frame_columns:])
            if _separation(ra, dec, solution.ra, solution.dec) <= radius:
                found.append((_frame(tuple(row)[:frame_columns]), solution))
                if len(found) == limit:
                    break
        return found

    def unsolved_lights(self, target: str) -> list[FrameRow]:
        """Lights of ``target`` (ignoring case) never tried, most stars first, then newest."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_FRAME_COLUMNS} {_FRAME_JOINS}"
                " LEFT JOIN solutions s ON s.frame_id = f.id"
                " WHERE t.name = ? AND f.frame_type = 'light' AND s.frame_id IS NULL"
                " ORDER BY coalesce(f.stars, -1) DESC, f.id DESC",
                (target,),
            ).fetchall()
        return [_frame(row) for row in rows]

    def nights(self, night_id: int | None = None) -> list[NightRow]:
        """Newest first, with what was saved in each, by type, target and filter."""
        where = "WHERE n.id = ?" if night_id is not None else ""
        args = (night_id,) if night_id is not None else ()
        with self._lock:
            nights = self._db.execute(
                f"SELECT id, night, site, first_frame, last_frame FROM nights n {where}"
                " ORDER BY night DESC",
                args,
            ).fetchall()
            groups = self._db.execute(
                "SELECT f.night_id, f.frame_type, t.name, f.filter, count(*), sum(f.size),"
                " sum(f.exposure)"
                f" FROM frames f LEFT JOIN targets t ON t.id = f.target_id"
                f" {where.replace('n.id', 'f.night_id')}"
                " GROUP BY f.night_id, f.frame_type, t.name, f.filter"
                " ORDER BY f.frame_type, t.name, f.filter",
                args,
            ).fetchall()
        by_night: dict[int, list[NightGroup]] = {}
        for night, frame_type, target, filter, count, size, exposure in groups:
            by_night.setdefault(night, []).append(
                NightGroup(frame_type, target, filter, count, size, exposure)
            )
        return [NightRow(*row, groups=by_night.get(row[0], [])) for row in nights]
