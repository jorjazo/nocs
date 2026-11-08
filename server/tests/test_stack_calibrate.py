"""Choosing a live stack's masters from the calibration library."""

from datetime import date

from test_calibration_library import SETUP, row

from nocs.calibration.library import Light
from nocs.stacking.calibrate import MOST, MasterSpec, plan

LIGHT = Light(SETUP, "L", 300.0, -10.0, date(2026, 10, 31))


def test_darks_and_flats_with_their_bias() -> None:
    darks = [row("dark") for _ in range(3)]
    flats = [row("flat", filter="L", exposure=2.0) for _ in range(4)]
    bias = [row("bias", exposure=0.001) for _ in range(5)]
    found = plan(LIGHT, darks + flats + bias + [row("flat", filter="R", exposure=2.0)])
    assert found.dark == MasterSpec("dark", tuple(sorted((d.id for d in darks), reverse=True)))
    assert found.flat is not None
    assert set(found.flat.frames) == {f.id for f in flats}
    assert found.flat_offset is not None
    assert found.flat_offset.kind == "bias"
    assert set(found.flat_offset.frames) == {b.id for b in bias}
    assert found.notes == ("darks: 3", "flats: 4")
    # Each master before the one that needs it.
    assert [s.kind for s in found.specs] == ["dark", "bias", "flat"]


def test_bias_when_there_are_no_darks() -> None:
    bias = [row("bias", exposure=0.001) for _ in range(2)]
    found = plan(LIGHT, bias)
    assert found.dark is not None
    assert found.dark.kind == "bias"
    assert found.flat is None
    assert found.notes == ("no darks; bias: 2", "no flats")


def test_flats_without_their_bias_are_not_used() -> None:
    darks = [row("dark") for _ in range(2)]
    flats = [row("flat", filter="L", exposure=2.0, gain=0.0) for _ in range(3)]
    found = plan(LIGHT, darks + flats)
    assert found.flat is None
    assert found.notes == ("darks: 2", "flats without their bias or dark flats: not used")


def test_flats_need_the_lights_pedestal_taken_off_first() -> None:
    # Flats with their bias, but nothing to take the lights' own pedestal off.
    flats = [row("flat", filter="L", exposure=2.0) for _ in range(2)]
    bias = [row("bias", exposure=0.001, gain=0.0) for _ in range(2)]
    found = plan(LIGHT, flats + bias)
    assert found.dark is None
    assert found.flat is None
    assert found.notes == ("no darks or bias", "flats need the lights' darks or bias: not used")


def test_dark_flats_serve_as_the_flats_offset() -> None:
    darks = [row("dark") for _ in range(2)]
    flats = [row("flat", filter="L", exposure=2.0) for _ in range(2)]
    dark_flats = [row("dark", exposure=2.0) for _ in range(2)]
    found = plan(LIGHT, darks + flats + dark_flats)
    assert found.flat_offset is not None
    assert found.flat_offset.kind == "dark"
    assert found.dark is not None
    assert set(found.dark.frames) == {d.id for d in darks}


def test_at_most_the_newest_frames() -> None:
    darks = [row("dark", f"2026-10-{day:02d}") for day in range(1, 31)]
    found = plan(LIGHT, darks)
    assert found.dark is not None
    assert len(found.dark.frames) == MOST
    assert found.dark.frames[0] == darks[-1].id


def test_the_same_frames_make_the_same_key() -> None:
    assert MasterSpec("dark", (3, 1, 2)).key == MasterSpec("dark", (1, 2, 3)).key
    assert MasterSpec("dark", (1, 2)).key != MasterSpec("bias", (1, 2)).key
    assert MasterSpec("dark", (1, 2)).key != MasterSpec("dark", (1, 3)).key


def test_a_master_is_named_by_everything_that_makes_it() -> None:
    flat = MasterSpec("flat", (1, 2, 3))
    name = flat.file_name("RGGB", "/data/masters/bias-a.fits")
    assert name.startswith("flat-")
    assert name.endswith(".fits")
    # Another bias under the flats, another Bayer pattern: another master.
    assert flat.file_name("RGGB", "/data/masters/bias-b.fits") != name
    assert flat.file_name("BGGR", "/data/masters/bias-a.fits") != name
    assert flat.file_name("RGGB", "/data/masters/bias-a.fits") == name
