"""Finding the Sun's or the Moon's disc in synthetic frames (ADR 0049)."""

import math
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from synthdisc import bayer, disc_frame

from nocs.imaging.disc import find_disc, locate


def _off(disc_x: float | None, disc_y: float | None, x: float, y: float) -> float:
    assert disc_x is not None
    assert disc_y is not None
    return math.hypot(disc_x - x, disc_y - y)


def test_a_whole_disc() -> None:
    disc = locate(disc_frame(x=410, y=300), color=False, radius=120)
    assert disc.found
    assert disc.method == "limb"
    assert _off(disc.x, disc.y, 410, 300) < 1.5
    assert disc.radius == pytest.approx(120, rel=0.03)
    assert (disc.width, disc.height) == (1200, 800)


@pytest.mark.parametrize(("phase", "angle"), [(0.5, 0), (0.25, 135), (0.12, 270), (0.8, 40)])
def test_a_phase_is_centred_on_its_disc_not_its_light(phase: float, angle: float) -> None:
    frame = disc_frame(x=650, y=380, phase=phase, angle=angle)
    disc = locate(frame, color=False, radius=120)
    assert disc.found
    assert _off(disc.x, disc.y, 650, 380) < 3


@pytest.mark.parametrize(("x", "y"), [(40, 400), (1180, 790), (600, -60), (-70, 300)])
def test_a_disc_cut_by_the_frame(x: float, y: float) -> None:
    disc = locate(disc_frame(x=x, y=y), color=False, radius=120)
    assert disc.found
    assert _off(disc.x, disc.y, x, y) < 3


def test_a_daylight_moon() -> None:
    frame = disc_frame(x=500, y=420, sky=26000, brightness=14000, noise=150, phase=0.6, angle=200)
    disc = locate(frame, color=False, radius=120)
    assert disc.found
    assert _off(disc.x, disc.y, 500, 420) < 3
    assert disc.background == pytest.approx(26000 / 65535, abs=0.02)


def test_a_saturated_disc() -> None:
    disc = locate(disc_frame(x=700, y=350, brightness=200000), color=False, radius=120)
    assert disc.found
    assert _off(disc.x, disc.y, 700, 350) < 1.5


def test_a_focal_length_a_little_off() -> None:
    disc = locate(disc_frame(radius=135), color=False, radius=120)
    assert disc.found
    assert disc.radius == pytest.approx(135, rel=0.03)


def test_a_bayer_frame_reduced_from_a_large_sensor() -> None:
    frame = bayer(disc_frame(3000, 2000, x=2100, y=900, radius=300))
    disc = locate(frame, color=True, radius=300)
    assert disc.found
    assert _off(disc.x, disc.y, 2100, 900) < 5
    assert disc.radius == pytest.approx(300, rel=0.03)


def test_a_small_disc_is_its_centroid() -> None:
    disc = locate(disc_frame(x=300.0, y=200.0, radius=3.0), color=False, radius=3.0)
    assert disc.found
    assert disc.method == "centroid"
    assert _off(disc.x, disc.y, 300, 200) < 1


def test_nothing_in_an_empty_sky() -> None:
    disc = locate(disc_frame(radius=0.0), color=False, radius=120)
    assert not disc.found
    assert disc.background == pytest.approx(1500 / 65535, abs=0.01)


def test_stars_are_not_a_disc() -> None:
    disc = locate(disc_frame(radius=0.0, stars=40), color=False, radius=120)
    assert not disc.found


def test_a_glow_is_not_a_disc() -> None:
    yy, xx = np.mgrid[0:800, 0:1200].astype(np.float64)
    glow = 3000 + 20000 * np.exp(-((xx + 300) ** 2 + (yy - 400) ** 2) / (2 * 600.0**2))
    disc = locate(glow.astype(np.uint16), color=False, radius=60)
    assert not disc.found


def test_the_disc_and_stars() -> None:
    disc = locate(disc_frame(x=500, y=500, stars=30), color=False, radius=120)
    assert disc.found
    assert _off(disc.x, disc.y, 500, 500) < 1.5


def test_from_a_fits_file(tmp_path: Path) -> None:
    path = tmp_path / "sun.fits"
    fits.PrimaryHDU(disc_frame(x=420, y=360)).writeto(path)  # pyright: ignore[reportUnknownMemberType]
    disc = find_disc(str(path), None, 120 / 1200)
    assert disc.found
    assert _off(disc.x, disc.y, 420, 360) < 1.5
    assert disc.seconds > 0
