"""Folder layout, file names and FITS headers of saved frames (ADR 0013)."""

from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]

from nocs.storage.fits import BLOCK, Card, FitsError, Header, place
from nocs.storage.layout import (
    DEFAULT_TEMPLATE,
    NameFields,
    TemplateError,
    check_template,
    clean,
    file_stem,
    folder,
    night_of,
)

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline

CHILE = -70.7  # local mean solar time is UTC - 4.7 h


@pytest.mark.parametrize(
    ("utc", "longitude", "night"),
    [
        ("2026-10-31T01:00", CHILE, "2026-10-30"),  # 20:18 local
        ("2026-10-31T10:00", CHILE, "2026-10-30"),  # 05:18 local, same night
        ("2026-10-31T17:00", CHILE, "2026-10-31"),  # 12:18 local, past noon
        ("2026-10-30T23:00", 139.7, "2026-10-30"),  # Tokyo, 08:18 on the 31st
        ("2026-10-31T10:00", 139.7, "2026-10-31"),  # Tokyo, 19:18
        ("2026-10-31T11:00", 0.0, "2026-10-30"),
        ("2026-10-31T12:00", 0.0, "2026-10-31"),
    ],
)
def test_night_changes_at_local_noon(utc: str, longitude: float, night: str) -> None:
    start = datetime.fromisoformat(utc).replace(tzinfo=UTC)
    assert night_of(start, longitude).isoformat() == night


def test_night_without_a_site_uses_the_system_time_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setenv("TZ", "America/Santiago")
    time.tzset()
    try:
        start = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)  # 07:00 in Santiago (UTC-3)
        assert night_of(start, None) == date(2026, 10, 30)
    finally:
        monkeypatch.undo()
        time.tzset()


@pytest.mark.parametrize(
    ("name", "cleaned"),
    [
        ("M 31", "M_31"),
        ("NGC 7000 / North America", "NGC_7000_North_America"),
        ("Nebulosa de Orión", "Nebulosa_de_Orión"),
        ('a:b*c?"d"<e>|f', "abcdef"),
        ("..hidden", "hidden"),
        ("  ", ""),
        ("x" * 100, "x" * 64),
    ],
)
def test_clean_names(name: str, cleaned: str) -> None:
    assert clean(name) == cleaned


def test_folders_by_frame_type() -> None:
    night = date(2026, 10, 30)
    assert folder("light", night, "M 31", "Ha") == PurePosixPath("2026-10-30/Light/M_31/Ha")
    assert folder("light", night, None, None) == PurePosixPath("2026-10-30/Light/Untitled")
    assert folder("flat", night, "M 31", "Ha") == PurePosixPath("2026-10-30/Flat/Ha")
    assert folder("flat", night, None, None) == PurePosixPath("2026-10-30/Flat")
    assert folder("dark", night, "M 31", "Ha") == PurePosixPath("2026-10-30/Dark")
    assert folder("bias", night, None, "L") == PurePosixPath("2026-10-30/Bias")


def fields(**changes: Any) -> NameFields:
    values: dict[str, Any] = {
        "target": "M31",
        "night": date(2026, 10, 30),
        "frame_type": "light",
        "filter": "Ha",
        "exposure": 300.0,
        "gain": 100.0,
        "offset": 10.0,
        "temperature": -9.8,
        "binning": 1,
        "camera": "ZWO CCD ASI2600MM Pro",
        "start": datetime(2026, 10, 31, 3, 15, 2, tzinfo=UTC),
        "seq": 7,
    }
    return NameFields(**(values | changes))


def test_default_file_name() -> None:
    assert file_stem(DEFAULT_TEMPLATE, fields()) == "20261031-031502_Light_Ha_300s_-10C_0007"


def test_empty_fields_drop_out_with_their_separators_and_units() -> None:
    stem = file_stem(DEFAULT_TEMPLATE, fields(filter=None, temperature=None, exposure=0.5))
    assert stem == "20261031-031502_Light_0.5s_0007"


def test_every_field() -> None:
    template = "{target}-{night}-{type}-{filter}-{exposure}-{gain}-{offset}-{temperature}-" + (
        "{binning}-{camera}-{datetime}-{seq}"
    )
    assert file_stem(check_template(template), fields()) == (
        "M31-2026-10-30-Light-Ha-300-100-10--10-1x1-ZWO_CCD_ASI2600MM_Pro-20261031-031502-0007"
    )


@pytest.mark.parametrize(
    "template",
    ["{nope}", "{seq:03d}", "{target!r}", "{target.upper}", "a/{seq}", "no fields", "{seq"],
)
def test_bad_templates(template: str) -> None:
    with pytest.raises(TemplateError):
        check_template(template)


# -- FITS headers --------------------------------------------------------------


def write_fits(path: Path, cards: int = 0, **header: Any) -> bytes:
    """A small 16-bit frame with ``cards`` filler cards, like INDI writes; returns its pixels."""
    data = np.arange(64 * 48, dtype=np.uint16).reshape(48, 64) * 13
    hdu = _fits.PrimaryHDU(data)
    for key, value in header.items():
        hdu.header[key.replace("_", "-")] = value
    for i in range(cards):
        hdu.header[f"FILL{i}"] = i
    hdu.writeto(path)
    raw = path.read_bytes()
    return raw[Header(path).length :]


def read_header(path: Path) -> Any:
    with _fits.open(path) as hdus:
        return hdus[0].header.copy()


def test_header_values(tmp_path: Path) -> None:
    path = tmp_path / "a.fits"
    write_fits(path, FILTER="Red     ", DATE_OBS="2026-10-30T18:58:43.486", CCD_TEMP=-9.5)
    header = Header(path)
    assert header.text("FILTER") == "Red"
    assert header.number("CCD-TEMP") == -9.5
    assert header.number("NAXIS1") == 64
    assert header.start() == datetime(2026, 10, 30, 18, 58, 43, 486000, tzinfo=UTC)
    assert header.number("FILTER") is None
    assert header.text("MISSING") is None


def test_header_is_completed_in_place_when_it_fits(tmp_path: Path) -> None:
    source = tmp_path / "in.fits"
    pixels = write_fits(source, FOCALLEN=250.0, OBJECT="driver")
    header = Header(source)
    assert header.length == BLOCK
    header.apply(
        [
            Card("FOCALLEN", 999.0, "ignored: the driver wrote it"),
            Card("OBJECT", "M31", "always NOCS's"),
            Card("SITEELEV", 2400.0, "added"),
        ],
        overwrite=frozenset({"OBJECT"}),
    )
    target = tmp_path / "out" / "frame.fits"
    target.parent.mkdir()
    inode = source.stat().st_ino
    place(source, header, target)
    assert not source.exists()
    assert target.stat().st_ino == inode  # renamed, not copied
    result = read_header(target)
    assert (result["FOCALLEN"], result["OBJECT"], result["SITEELEV"]) == (250.0, "M31", 2400.0)
    assert target.read_bytes()[BLOCK:] == pixels


def test_header_that_outgrows_its_blocks_is_written_once_at_the_target(tmp_path: Path) -> None:
    source = tmp_path / "in.fits"
    pixels = write_fits(source, cards=27)  # 8 mandatory + 27 + END: one block, no room left
    header = Header(source)
    assert header.length == BLOCK
    header.apply([Card(f"NEW{i}", i, "") for i in range(5)], overwrite=frozenset())
    target = tmp_path / "frame.fits"
    place(source, header, target)
    assert not source.exists()
    assert Header(target).length == 2 * BLOCK
    assert read_header(target)["NEW4"] == 4
    assert target.read_bytes()[2 * BLOCK :] == pixels
    with _fits.open(target) as hdus:
        assert int(hdus[0].data[1, 2]) == (64 + 2) * 13  # scaling untouched


def test_place_never_overwrites(tmp_path: Path) -> None:
    source, target = tmp_path / "in.fits", tmp_path / "taken.fits"
    write_fits(source)
    target.write_bytes(b"precious")
    with pytest.raises(FileExistsError):
        place(source, Header(source), target)
    assert target.read_bytes() == b"precious"
    assert source.exists()


def test_not_fits(tmp_path: Path) -> None:
    path = tmp_path / "x.fits"
    path.write_bytes(b"\0" * BLOCK)
    with pytest.raises(FitsError):
        Header(path)
    path.write_bytes(b"SIMPLE")
    with pytest.raises(FitsError):
        Header(path)
