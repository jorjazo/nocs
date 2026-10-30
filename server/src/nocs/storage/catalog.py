"""The SQLite catalog of saved frames: volumes, targets, nights and frames (ADR 0013).

One connection, used from worker threads one at a time (every method blocks).
The schema version lives in ``PRAGMA user_version``; ``MIGRATIONS[n]`` takes a
database from version ``n`` to ``n + 1``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath

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
class FrameFilter:
    night: int | None = None
    target: str | None = None
    frame_type: str | None = None
    filter: str | None = None
    before: int | None = None
    limit: int | None = None


_FRAME_COLUMNS = """
    f.id, n.night, t.name, v.key, v.label, f.directory, f.path, f.size, f.started,
    f.exposure, f.frame_type, f.filter, f.profile, f.camera, f.gain, f."offset", f.binning,
    f.temperature, f.width, f.height, f.stars, f.hfr
"""
_FRAME_JOINS = """
    FROM frames f
    JOIN nights n ON n.id = f.night_id
    JOIN volumes v ON v.id = f.volume_id
    LEFT JOIN targets t ON t.id = f.target_id
"""


def _frame(row: sqlite3.Row) -> FrameRow:
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
                    " binning, temperature, width, height)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    # -- reading ----------------------------------------------------------

    def frame(self, frame_id: int) -> FrameRow | None:
        with self._lock:
            row = self._db.execute(
                f"SELECT {_FRAME_COLUMNS} {_FRAME_JOINS} WHERE f.id = ?", (frame_id,)
            ).fetchone()
        return _frame(row) if row is not None else None

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
