"""The SQLite frame catalog and its schema migrations (ADR 0013)."""

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import pytest

from nocs.storage import catalog
from nocs.storage.catalog import (
    Catalog,
    CatalogError,
    FocusRun,
    FrameFilter,
    NewFrame,
    TemperatureSample,
)

FRAME = NewFrame(
    night=date(2026, 10, 30),
    site="Lab",
    target="M31",
    volume="1234-ABCD",
    volume_label="SSD",
    mount_point="/media/nocs/SSD",
    directory=PurePosixPath(""),
    path=PurePosixPath("2026-10-30/Light/M31/Ha/a.fits"),
    size=1000,
    started=datetime(2026, 10, 31, 1, 0, tzinfo=UTC),
    exposure=300,
    frame_type="light",
    filter="Ha",
    profile="lab",
    camera="ZWO CCD ASI2600MM Pro",
    gain=100,
    offset=10,
    binning=1,
    temperature=-10,
    width=6248,
    height=4176,
)


@pytest.fixture
def db(tmp_path: Path) -> Catalog:
    return Catalog(tmp_path / "catalog.sqlite")


def test_new_catalog_is_at_the_latest_version(db: Catalog) -> None:
    assert db.version == catalog.VERSION


def test_frames_nights_and_metrics(db: Catalog) -> None:
    first = db.add_frame(FRAME)
    second = db.add_frame(
        replace(
            FRAME,
            path=PurePosixPath("2026-10-30/Light/M31/Ha/b.fits"),
            target="m31",  # same target, other spelling
            started=datetime(2026, 10, 31, 2, 0, tzinfo=UTC),
        )
    )
    flat = db.add_frame(
        replace(
            FRAME,
            path=PurePosixPath("2026-10-30/Flat/Ha/f.fits"),
            target=None,
            frame_type="flat",
            exposure=2,
            started=datetime(2026, 10, 31, 9, 0, tzinfo=UTC),
        )
    )
    other_night = db.add_frame(
        replace(FRAME, night=date(2026, 10, 31), path=PurePosixPath("2026-10-31/Light/M31/a"))
    )
    db.set_metrics(first, 812, 2.31)

    row = db.frame(first)
    assert row is not None
    assert (row.night, row.target, row.volume, row.volume_label) == (
        "2026-10-30",
        "M31",
        "1234-ABCD",
        "SSD",
    )
    assert (row.stars, row.hfr, row.path) == (812, 2.31, FRAME.path)
    assert db.frame(9999) is None

    assert [f.id for f in db.frames(FrameFilter())] == [other_night, flat, second, first]
    [night, newer] = sorted(db.nights(), key=lambda n: n.night)
    assert newer.night == "2026-10-31"
    assert (night.first_frame, night.last_frame) == (
        "2026-10-31T01:00:00.000+00:00",
        "2026-10-31T09:00:00.000+00:00",
    )
    assert [(g.frame_type, g.target, g.frames, g.size, g.exposure) for g in night.groups] == [
        ("flat", None, 1, 1000, 2),
        ("light", "M31", 2, 2000, 600),
    ]
    by_night = FrameFilter(night=night.id)
    assert [f.id for f in db.frames(by_night)] == [flat, second, first]
    assert [f.id for f in db.frames(replace(by_night, frame_type="light", target="m31"))] == [
        second,
        first,
    ]
    assert [f.id for f in db.frames(replace(by_night, before=second, limit=5))] == [first]
    assert [f.id for f in db.frames(FrameFilter(filter="OIII"))] == []
    assert [n.id for n in db.nights(night.id)] == [night.id]


def test_target_spelling_is_kept(db: Catalog) -> None:
    assert db.target("M31") == "M31"
    assert db.target("m31") == "M31"


def test_a_name_saved_again_replaces_its_old_row(db: Catalog) -> None:
    old = db.add_frame(FRAME)
    new = db.add_frame(replace(FRAME, size=2000))
    assert db.frame(old) is None
    row = db.frame(new)
    assert row is not None
    assert row.size == 2000


def test_newer_schema_is_left_untouched(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(path) as raw:
        raw.execute(f"PRAGMA user_version = {catalog.VERSION + 1}")
    with pytest.raises(CatalogError, match="newer"):
        Catalog(path)
    with sqlite3.connect(path) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == catalog.VERSION + 1
        assert raw.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0


def test_migration_backs_up_and_upgrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "catalog.sqlite"
    db = Catalog(path)
    frame_id = db.add_frame(FRAME)
    db.close()

    step = "ALTER TABLE frames ADD COLUMN fwhm REAL; UPDATE frames SET fwhm = 3.5;"
    monkeypatch.setattr(catalog, "MIGRATIONS", [*catalog.MIGRATIONS, step])
    monkeypatch.setattr(catalog, "VERSION", catalog.VERSION + 1)
    upgraded = Catalog(path)
    assert upgraded.version == catalog.VERSION
    assert upgraded.frame(frame_id) is not None
    upgraded.close()
    with sqlite3.connect(path) as raw:
        assert raw.execute("SELECT fwhm FROM frames").fetchone()[0] == 3.5
    backup = tmp_path / f"catalog.sqlite.v{catalog.VERSION - 1}.bak"
    with sqlite3.connect(backup) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == catalog.VERSION - 1
        assert raw.execute("SELECT count(*) FROM frames").fetchone()[0] == 1


def test_failed_migration_keeps_the_previous_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "catalog.sqlite"
    Catalog(path).close()
    broken = "ALTER TABLE frames ADD COLUMN fwhm REAL; SELECT * FROM no_such_table;"
    monkeypatch.setattr(catalog, "MIGRATIONS", [*catalog.MIGRATIONS, broken])
    monkeypatch.setattr(catalog, "VERSION", catalog.VERSION + 1)
    with pytest.raises(sqlite3.OperationalError):
        Catalog(path)
    with sqlite3.connect(path) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == catalog.VERSION - 1
        columns = [row[1] for row in raw.execute("PRAGMA table_info(frames)")]
        assert "fwhm" not in columns


def test_temperatures_are_kept_by_time(db: Catalog) -> None:
    for minute, focuser in ((0, 8.5), (1, 8.4), (2, 8.2)):
        db.add_temperature(
            TemperatureSample(f"2026-10-31T02:0{minute}:00+00:00", focuser, 11.0, 70.0, 5.9)
        )
    db.add_temperature(TemperatureSample("2026-10-31T02:02:00+00:00", 8.1, None, None, None))
    samples = db.temperatures("2026-10-31T02:01:00+00:00")
    assert [(s.time[11:16], s.focuser, s.ambient) for s in samples] == [
        ("02:01", 8.4, 11.0),
        ("02:02", 8.1, None),  # the same time again replaces the sample
    ]
    assert len(db.temperatures("2026-10-31T00:00:00+00:00", "2026-10-31T02:01:00+00:00")) == 1


def test_focus_runs_newest_first(db: Catalog) -> None:
    run = FocusRun(
        started="2026-10-31T02:00:00.000+00:00",
        finished="2026-10-31T02:01:10.000+00:00",
        profile="lab",
        filter="L",
        state="succeeded",
        problem=None,
        start_position=31000,
        position=30875,
        start_hfr=2.4,
        hfr=1.9,
        focuser_temperature=8.4,
        ambient_temperature=11.0,
        run='{"points": []}',
    )
    first = db.add_focus_run(run)
    second = db.add_focus_run(replace(run, state="failed", problem="no_stars", position=None))
    runs = db.focus_runs()
    assert [(r.id, r.state, r.problem) for r in runs] == [
        (second, "failed", "no_stars"),
        (first, "succeeded", None),
    ]
    assert runs[1] == replace(run, id=first)
    assert db.focus_runs(limit=1, before=second) == [replace(run, id=first)]


def test_version_1_catalogs_gain_the_night_tables(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(path) as raw:
        raw.executescript(catalog.MIGRATIONS[0] + "PRAGMA user_version = 1;")
    db = Catalog(path)
    assert db.version == catalog.VERSION
    assert db.focus_runs() == []
    assert db.temperatures("2026-01-01") == []
    db.close()
