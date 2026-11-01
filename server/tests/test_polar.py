"""Polar alignment math against a simulated mount, in both hemispheres.

A mount with a polar error is the aligned one with its knobs turned: its frames are
the aligned mount's directions (hour angle and Dec on its own axis) turned with
``turn``. Its sign conventions match the INDI telescope simulator's ``MOUNT_MODEL``
in the south (ADR 0034): ``MM_ME`` +60' fitted 60' above the pole, ``MM_MA`` +60'
60' east of it.
"""

import math
from datetime import UTC, datetime

import numpy as np
import pytest

from nocs.align.polar import (
    Vector,
    angles,
    direction,
    fit_axis,
    knobs,
    polar_error,
    pole,
    rotation,
    sensitivity,
    track,
    turn,
    vector,
    zenith,
)
from nocs.devices import Location
from nocs.mount.coords import j2000_to_jnow, jnow_to_horizontal, sidereal_time

DIAGUITAS = Location(-30.0277, -70.6733, 700)
NORTH = Location(45.0, 7.0, 300)
WHEN = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)


def mount(
    latitude: float, altitude: float, azimuth: float, hour_angle: float, dec: float
) -> Vector:
    """Where a mount with that error (arcminutes) points at its own hour angle and Dec."""
    p = pole(latitude)
    return turn(vector(hour_angle, dec), p, latitude, altitude=altitude, azimuth=azimuth)


def axis_of(latitude: float, altitude: float, azimuth: float) -> Vector:
    p = pole(latitude)
    return turn(p, p, latitude, altitude=altitude, azimuth=azimuth)


def three_points(latitude: float, altitude: float, azimuth: float, dec: float) -> list[Vector]:
    """Turned 30° twice westwards from the meridian."""
    return [mount(latitude, altitude, azimuth, h, dec) for h in (0.0, 2.0, 4.0)]


def test_vectors_and_angles() -> None:
    assert np.allclose(vector(0, DIAGUITAS.latitude), zenith(DIAGUITAS.latitude))
    assert np.allclose(vector(-6, 0), [0, 1, 0])  # east
    assert np.allclose(vector(0, 90), [0, 0, 1])
    h, d = angles(vector(-3.5, -42.0))
    assert h == pytest.approx(-3.5)
    assert d == pytest.approx(-42.0)


@pytest.mark.parametrize("site", [DIAGUITAS, NORTH])
def test_direction_agrees_with_the_local_sky(site: Location) -> None:
    """A solution's direction has the altitude and azimuth ERFA gives it."""
    ra, dec = 0.7925, -25.288  # NGC 253
    v = direction(ra, dec, site, WHEN)
    jnow = j2000_to_jnow(ra, dec, WHEN)
    sky = jnow_to_horizontal(jnow.ra, jnow.dec, site, WHEN)
    phi = math.radians(site.latitude)
    up = zenith(site.latitude)
    north = np.array([-math.sin(phi), 0.0, math.cos(phi)])
    alt = math.degrees(math.asin(float(v @ up)))
    az = math.degrees(math.atan2(float(v[1]), float(v @ north))) % 360
    assert alt == pytest.approx(sky.alt, abs=1 / 3600)
    assert az == pytest.approx(sky.az, abs=1 / 3600 / max(math.cos(math.radians(alt)), 0.1))


def test_sidereal_time_moves_with_the_sky() -> None:
    later = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
    hours = (sidereal_time(0.0, later) - sidereal_time(0.0, WHEN)) % 24
    assert hours == pytest.approx(1.0027379, abs=1e-6)
    assert sidereal_time(15.0, WHEN) == pytest.approx((sidereal_time(0.0, WHEN) + 1) % 24)


@pytest.mark.parametrize("site", [DIAGUITAS, NORTH])
@pytest.mark.parametrize(
    ("altitude", "azimuth"),
    [(0, 0), (1, 0), (0, -1), (12, 4), (-45, 30), (60, -60), (-180, 240), (300, 300)],
)
def test_three_points_give_the_axis_and_its_error(
    site: Location, altitude: float, azimuth: float
) -> None:
    lat = site.latitude
    dec = -60.0 if lat < 0 else 60.0
    axis = fit_axis(three_points(lat, altitude, azimuth, dec), lat)
    expected = polar_error(axis_of(lat, altitude, azimuth), lat)
    error = polar_error(axis, lat)
    assert error.altitude == pytest.approx(expected.altitude, abs=1e-6)
    assert error.azimuth == pytest.approx(expected.azimuth, abs=1e-6)
    # The knobs' amounts are the error, to within 3% (second order in it: 2.5% at 5°).
    assert error.altitude == pytest.approx(altitude, abs=0.03 * abs(altitude) + 1e-6)
    assert error.azimuth == pytest.approx(azimuth, abs=0.03 * abs(azimuth) + 1e-6)
    assert error.total == pytest.approx(math.hypot(altitude, azimuth), rel=0.03, abs=1e-6)


def test_the_axis_points_at_the_elevated_pole() -> None:
    for site in (DIAGUITAS, NORTH):
        points = three_points(site.latitude, 20, -10, 30.0)
        assert float(fit_axis(points, site.latitude) @ pole(site.latitude)) > 0
        assert float(fit_axis(points[::-1], site.latitude) @ pole(site.latitude)) > 0


def test_the_simulators_mount_model() -> None:
    """EQUATORIAL_PE of the telescope simulator at Diaguitas, 2026-11-01, at its
    hour angles 0, 2 and 4 h, Dec -30° (LST, RA hours; Dec degrees)."""
    lat = DIAGUITAS.latitude
    elevation = [
        (0.12230, 0.11416, -29.0000),
        (0.12488, 22.14110, -29.1331),
        (0.12741, 20.15775, -29.4968),
    ]
    azimuth = [
        (0.15147, 0.18180, -29.9971),
        (0.15398, 22.18521, -30.4968),
        (0.15655, 20.17363, -30.8651),
    ]
    me = polar_error(fit_axis([vector(t - r, d) for t, r, d in elevation], lat), lat)
    ma = polar_error(fit_axis([vector(t - r, d) for t, r, d in azimuth], lat), lat)
    assert (me.altitude, me.azimuth) == pytest.approx((60, 0), abs=0.1)  # MM_ME = 60
    assert (ma.altitude, ma.azimuth) == pytest.approx((0, 60), abs=0.5)  # MM_MA = 60


def test_noisy_solves() -> None:
    """3" of noise on each solve: the axis within 1' (30° steps grow it ~9 times)."""
    rng = np.random.default_rng(7)
    lat = DIAGUITAS.latitude
    worst = 0.0
    for _ in range(50):
        points = [
            p + rng.normal(0, math.radians(3 / 3600), 3) for p in three_points(lat, 25, -15, -60)
        ]
        error = polar_error(fit_axis(points, lat), lat)
        worst = max(worst, math.hypot(error.altitude - 25, error.azimuth + 15))
    assert worst < 1.2


def test_points_in_one_place_are_refused() -> None:
    lat = DIAGUITAS.latitude
    p = vector(1, -50)
    with pytest.raises(ValueError, match="too close"):
        fit_axis([p, p, p], lat)
    with pytest.raises(ValueError, match="at least three"):
        fit_axis([p, vector(2, -50)], lat)


def test_rotation_about_the_axis() -> None:
    lat = DIAGUITAS.latitude
    points = three_points(lat, 40, 20, -45)
    axis = fit_axis(points, lat)
    assert rotation(axis, points[0], points[1]) == pytest.approx(30, abs=1e-6)
    assert rotation(axis, points[2], points[0]) == pytest.approx(-60, abs=1e-6)
    north = three_points(NORTH.latitude, 40, 20, 45)
    assert rotation(fit_axis(north, NORTH.latitude), north[0], north[2]) == pytest.approx(60)


@pytest.mark.parametrize("site", [DIAGUITAS, NORTH])
def test_tracking_follows_the_sky_on_an_aligned_mount(site: Location) -> None:
    p = pole(site.latitude)
    start = vector(1.0, -50 if site.latitude < 0 else 50)
    hour = track(start, p, 3600)
    h0, d0 = angles(start)
    h1, d1 = angles(hour)
    assert h1 - h0 == pytest.approx(1.0027379, abs=1e-6)
    assert d1 == pytest.approx(d0)


@pytest.mark.parametrize("site", [DIAGUITAS, NORTH])
@pytest.mark.parametrize(("up", "east"), [(-30, 10), (5, -2), (120, 90), (-0.5, 0.3)])
def test_a_knob_turn_shows_in_the_next_frame(site: Location, up: float, east: float) -> None:
    lat = site.latitude
    dec = -60.0 if lat < 0 else 60.0
    error = (40.0, -25.0)
    true_axis = axis_of(lat, *error)
    reference = mount(lat, *error, 4.0, dec)
    seconds = 20.0
    after = turn(track(reference, true_axis, seconds), true_axis, lat, altitude=up, azimuth=east)
    fitted = fit_axis(three_points(lat, *error, dec), lat)
    turned = knobs(reference, after, fitted, lat, seconds)
    assert turned.altitude == pytest.approx(up, abs=1e-3)
    assert turned.azimuth == pytest.approx(east, abs=1e-3)
    now = polar_error(turn(fitted, fitted, lat, altitude=up, azimuth=east), lat)
    truth = polar_error(turn(true_axis, true_axis, lat, altitude=up, azimuth=east), lat)
    assert (now.altitude, now.azimuth) == pytest.approx((truth.altitude, truth.azimuth), abs=1e-3)


def test_turning_the_knobs_by_the_error_aligns_the_mount() -> None:
    """The user follows the readout in a few steps, frame by frame."""
    lat = DIAGUITAS.latitude
    error = (90.0, -150.0)
    true_axis = axis_of(lat, *error)
    axis = fit_axis(three_points(lat, *error, -60), lat)
    frame = mount(lat, *error, 4.0, -60)
    for _ in range(4):
        shown = polar_error(axis, lat)
        # Each time the user turns the knobs 80% of the way and the axis follows.
        up, east = -0.8 * shown.altitude, -0.8 * shown.azimuth
        after = turn(track(frame, true_axis, 5), true_axis, lat, altitude=up, azimuth=east)
        true_axis = turn(true_axis, true_axis, lat, altitude=up, azimuth=east)
        turned = knobs(frame, after, axis, lat, 5)
        axis = turn(axis, axis, lat, altitude=turned.altitude, azimuth=turned.azimuth)
        frame = after
    final = polar_error(axis, lat)
    truth = polar_error(true_axis, lat)
    assert final.total < 1.0
    assert (final.altitude, final.azimuth) == pytest.approx(
        (truth.altitude, truth.azimuth), abs=0.01
    )


def test_sensitivity_is_lost_due_east_and_at_the_zenith() -> None:
    lat = DIAGUITAS.latitude
    p = pole(lat)
    assert sensitivity(zenith(lat), p, lat) < 0.01
    assert sensitivity(_due_east(lat, 40), p, lat) < 0.01
    assert sensitivity(vector(0, -60), p, lat) > 0.5  # the meridian, between zenith and pole
    assert sensitivity(vector(4, -60), p, lat) > 0.6


def _due_east(latitude: float, altitude: float) -> Vector:
    """A point due east at that altitude."""
    up = zenith(latitude)
    east = np.array([0.0, 1.0, 0.0])
    a = math.radians(altitude)
    return east * math.cos(a) + up * math.sin(a)
