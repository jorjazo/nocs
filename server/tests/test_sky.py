# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Tonight's sky against published almanacs.

Reference times are the U.S. Naval Observatory's (aa.usno.navy.mil, yearly tables
and the moon phases API, retrieved 2026-10-31), given to the minute for sea level.
The site is the one USNO rounds Cerro Tololo to (W070°49', S30°10'); Tromsø
(N69°39', E18°58') for the polar cases. Transits were checked against astropy.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.config import Settings
from nocs.devices import Location
from nocs.equipment import HorizonPoint, Profile, ProfileStore, Site
from nocs.sky import Target, horizon_altitude, night, tonight, visibility
from nocs.sky.almanac import TWILIGHTS
from nocs.sky.ephemeris import illumination, pressure, refraction, sky

TOLOLO = Location(-(30 + 10 / 60), -(70 + 49 / 60), 0)
TROMSO = Location(69 + 39 / 60, 18 + 58 / 60, 0)
DIAGUITAS = Location(-30.03, -70.67, 700)
HILL = [
    HorizonPoint(azimuth=0, altitude=30),
    HorizonPoint(azimuth=60, altitude=10),
    HorizonPoint(azimuth=300, altitude=10),
]
NGC_292 = Target(0.8818, -72.8)  # the Small Magellanic Cloud
NGC_253 = Target(0.7925, -25.288)
M_31 = Target(0.7123, 41.269)

MINUTE = 60.0


def at(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()


def near(value: float | None, text: str, tolerance: float = MINUTE) -> bool:
    return value is not None and abs(value - at(text)) <= tolerance


# -- Almanac --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (
            date(2026, 11, 15),
            {
                "sunset": "2026-11-15T23:17",
                "sunrise": "2026-11-16T09:38",
                "civil": ("2026-11-15T23:44", "2026-11-16T09:12"),
                "nautical": ("2026-11-16T00:15", "2026-11-16T08:41"),
                "astronomical": ("2026-11-16T00:48", "2026-11-16T08:08"),
            },
        ),
        (
            date(2026, 6, 15),
            {
                "sunset": "2026-06-15T21:50",
                "sunrise": "2026-06-16T11:38",
                "civil": ("2026-06-15T22:16", "2026-06-16T11:11"),
                "nautical": ("2026-06-15T22:46", "2026-06-16T10:42"),
                "astronomical": ("2026-06-15T23:16", "2026-06-16T10:12"),
            },
        ),
    ],
)
def test_sun_matches_usno(day: date, expected: dict[str, str | tuple[str, str]]) -> None:
    n = night(TOLOLO, day)
    assert near(n.sunset, str(expected["sunset"]))
    assert near(n.sunrise, str(expected["sunrise"]))
    for name in TWILIGHTS:
        interval = n.twilights[name]
        dusk, dawn = expected[name]
        assert interval is not None
        assert near(interval.start, dusk), name
        assert near(interval.end, dawn), name
    assert n.darkness == "astronomical"
    assert n.dark == n.twilights["astronomical"]


@pytest.mark.parametrize(
    ("day", "moonset", "moonrise"),
    [
        (date(2026, 11, 15), "2026-11-16T04:38", "2026-11-16T15:30"),
        (date(2026, 6, 15), "2026-06-15T22:24", "2026-06-16T13:22"),
    ],
)
def test_moon_rise_and_set_match_usno(day: date, moonset: str, moonrise: str) -> None:
    moon = night(TOLOLO, day).moon
    assert near(moon.set, moonset)
    assert near(moon.rise, moonrise)


@pytest.mark.parametrize(
    ("when", "phase", "fraction"),
    [
        ("2026-11-09T07:02", 0, 0.0),
        ("2026-11-17T11:48", 90, 0.5),
        ("2026-11-24T14:53", 180, 1.0),
        ("2026-12-01T06:08", 270, 0.5),
    ],
)
def test_moon_phases_match_usno(when: str, phase: float, fraction: float) -> None:
    s = sky(TOLOLO, [at(when)])
    lit, angle = illumination(s.sun.geocentric, s.moon.geocentric)
    # The Moon's elongation changes by 0.05° in about 6 minutes.
    assert abs((angle[0] - phase + 180) % 360 - 180) < 0.05
    assert abs(lit[0] - fraction) < 0.01


def test_moon_in_the_almanac() -> None:
    n = night(TOLOLO, date(2026, 11, 15))
    # Waxing crescent, first quarter on the 17th; set before dawn.
    assert 0.3 < n.moon.fraction < 0.45
    assert 60 < n.moon.phase < 90
    assert near(n.moon.up[0].end, "2026-11-16T04:38")
    assert n.dark is not None
    assert len(n.dark_moonless) == 1
    assert near(n.dark_moonless[0].start, "2026-11-16T04:38")
    assert n.dark_moonless[0].end == n.dark.end


def test_chart_runs_from_sunset_to_sunrise_every_ten_minutes() -> None:
    n = night(TOLOLO, date(2026, 11, 15))
    times = n.sky.times
    assert set(np.diff(times)) == {600.0}
    assert times[0] % 600 == 0
    assert n.sunset is not None
    assert n.sunrise is not None
    assert times[0] <= n.sunset < times[0] + 1200
    assert times[-1] - 1200 < n.sunrise <= times[-1]


def test_the_night_changes_at_local_noon() -> None:
    # Local mean noon at -70.82° is 16:43 UTC.
    assert tonight(TOLOLO, datetime(2026, 11, 16, 16, 40, tzinfo=UTC)) == date(2026, 11, 15)
    assert tonight(TOLOLO, datetime(2026, 11, 16, 16, 46, tzinfo=UTC)) == date(2026, 11, 16)


def test_midnight_sun_has_no_night() -> None:
    n = night(TROMSO, date(2026, 6, 21))
    assert n.below_horizon is None
    assert (n.sunset, n.sunrise) == (None, None)
    assert all(interval is None for interval in n.twilights.values())
    assert (n.darkness, n.dark, n.dark_moonless) == (None, None, [])
    assert n.lowest[1] > 0
    assert n.sky.times[0] <= n.span.start
    assert n.sky.times[-1] >= n.span.end
    v = visibility(n, [Target(18, 60)])[0]
    assert (v.windows, v.above_minimum, v.moon_separation_min) == ([], 0, None)


def test_polar_night_is_dark_all_through() -> None:
    n = night(TROMSO, date(2026, 12, 21))
    assert n.below_horizon == n.span
    assert (n.sunset, n.sunrise) == (None, None)
    assert n.darkness == "astronomical"
    assert n.dark is not None
    assert near(n.dark.start, "2026-12-21T15:56")
    assert near(n.dark.end, "2026-12-22T05:29")


def test_white_nights_fall_back_to_nautical_darkness() -> None:
    n = night(TROMSO, date(2026, 9, 10))
    assert n.twilights["astronomical"] is None
    assert n.darkness == "nautical"
    assert n.dark == n.twilights["nautical"]


def test_refraction_and_elevation() -> None:
    sea = refraction(np.array([-0.57, 0.0, 45.0, 90.0]), pressure(0))
    assert abs(sea[0] * 60 - 34.5) < 0.5  # the almanacs' 34' at the horizon
    assert abs(sea[2] * 60 - 1.0) < 0.05
    assert abs(sea[3]) < 1e-3
    assert 925 < pressure(700) < 935
    # Thinner air at 700 m: sunset a little earlier than at sea level.
    high = night(Location(TOLOLO.latitude, TOLOLO.longitude, 700), date(2026, 11, 15))
    low = night(TOLOLO, date(2026, 11, 15))
    assert high.sunset is not None
    assert low.sunset is not None
    assert 5 < low.sunset - high.sunset < 30


# -- Visibility ---------------------------------------------------------------------


def test_exit_targets_from_diaguitas() -> None:
    n = night(DIAGUITAS, date(2026, 11, 15))
    smc, sculptor = visibility(n, [NGC_292, NGC_253], horizon=HILL)
    assert n.dark is not None

    # Transits checked against astropy (geometric altitudes 47.37° and 85.11°).
    assert near(smc.transit, "2026-11-16T01:55:57", 2)
    assert abs(smc.transit_altitude - 47.39) < 0.02
    assert near(sculptor.transit, "2026-11-16T01:50:56", 2)
    assert abs(sculptor.transit_altitude - 85.12) < 0.02

    # Both are up from the start of the dark window; NGC 253 sinks below 30° first,
    # and then behind the hill in the west before dawn; the SMC never does.
    for v in (smc, sculptor):
        assert v.best is not None
        assert v.best.start == n.dark.start
    assert smc.above_horizon == pytest.approx(n.dark.duration)
    assert 6 * 3600 < sculptor.above_horizon < n.dark.duration - 60
    assert smc.best is not None
    assert sculptor.best is not None
    assert near(smc.best.end, "2026-11-16T07:35", 5 * MINUTE)
    assert near(sculptor.best.end, "2026-11-16T06:24", 5 * MINUTE)
    assert smc.above_minimum == pytest.approx(smc.observable)
    assert 50 < sculptor.moon_separation < 65
    assert sculptor.moon_separation_min is not None
    assert sculptor.moon_separation_min <= sculptor.moon_separation


def test_the_hill_hides_m31() -> None:
    n = night(DIAGUITAS, date(2026, 11, 15))
    flat = visibility(n, [M_31], min_altitude=0)[0]
    hill = visibility(n, [M_31], min_altitude=0, horizon=HILL)[0]
    # It culminates at ~19° due north, behind the hill (30° there).
    assert abs(flat.transit_altitude - 18.59) < 0.02
    north = float(flat.azimuth[np.argmax(flat.altitude)])
    assert min(north, 360 - north) < 5
    assert flat.above_horizon > 3 * 3600
    assert (hill.above_horizon, hill.windows, hill.best) == (0, [], None)
    assert hill.above_minimum == flat.above_minimum


def test_never_rising_and_circumpolar_targets() -> None:
    n = night(DIAGUITAS, date(2026, 11, 15))
    assert n.dark is not None
    north, south_pole = visibility(n, [Target(12, 80), Target(6, -89)], min_altitude=20)
    assert north.altitude.max() < 0
    assert (north.above_horizon, north.windows) == (0, [])
    assert south_pole.observable == pytest.approx(n.dark.duration)
    assert abs(south_pole.altitude.max() - south_pole.altitude.min()) < 2.5


def test_horizon_profile_interpolates_all_round() -> None:
    azimuths = np.array([0, 30, 60, 180, 300, 330, 359])
    assert horizon_altitude(HILL, azimuths).tolist() == pytest.approx(
        [30, 20, 10, 10, 10, 20, 30 - 20 / 60]
    )
    assert horizon_altitude(None, azimuths).tolist() == [0] * 7
    assert horizon_altitude([HorizonPoint(azimuth=90, altitude=5)], azimuths).tolist() == [5] * 7


def test_site_horizon_is_sorted_and_checked() -> None:
    site = Site(
        latitude=-30,
        longitude=-70,
        horizon=[HorizonPoint(azimuth=200, altitude=5), HorizonPoint(azimuth=10, altitude=20)],
    )
    assert [p.azimuth for p in site.horizon or []] == [10, 200]
    with pytest.raises(ValueError, match="same azimuth"):
        Site(
            latitude=0,
            longitude=0,
            horizon=[HorizonPoint(azimuth=10, altitude=1), HorizonPoint(azimuth=10, altitude=2)],
        )
    with pytest.raises(ValueError, match="at least one"):
        Site(latitude=0, longitude=0, horizon=[])
    with pytest.raises(ValueError, match="less than 360"):
        HorizonPoint(azimuth=360, altitude=0)


def test_the_example_profile_has_a_hill() -> None:
    path = Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json"
    site = Profile.model_validate_json(path.read_text()).site
    assert site is not None
    assert site.horizon is not None
    assert horizon_altitude(site.horizon, np.array([0.0]))[0] == 30


# -- API ------------------------------------------------------------------------


@pytest.fixture
def client(config_dir: Path) -> Iterator[TestClient]:
    profiles = ProfileStore(config_dir)
    site = Site(name="Lab", latitude=-30.03, longitude=-70.67, elevation=700, horizon=HILL)
    profiles.put("lab", Profile(name="Lab", site=site))
    profiles.active = "lab"
    with TestClient(create_app(Settings(indi_host="127.0.0.1", indi_port=9))) as client:
        pair_owner(client)
        yield client


def test_almanac_endpoint(client: TestClient) -> None:
    response = client.get("/api/sky/tonight", params={"date": "2026-11-15"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["night"] == "2026-11-15"
    assert body["site"]["name"] == "Lab"
    assert body["darkness"] == "astronomical"
    assert body["dark"] == body["astronomical"]
    assert body["sunset"].startswith("2026-11-15T23:")
    assert len(body["times"]) == len(body["sun_altitude"]) == len(body["moon"]["altitude"])
    assert body["moon"]["set"].startswith("2026-11-16T04:")


def test_almanac_defaults_to_tonight(client: TestClient) -> None:
    body = client.get("/api/sky/tonight").json()
    expected = tonight(DIAGUITAS, datetime.now(UTC))
    assert body["night"] == expected.isoformat()


def test_visibility_endpoint(client: TestClient) -> None:
    response = client.get(
        "/api/sky/visibility",
        params={"target": ["0.8818,-72.8", "0.7123,41.269"], "date": "2026-11-15"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["min_altitude"] == 30
    smc, m31 = body["targets"]
    assert smc["target"] == "0.8818,-72.8"
    assert smc["transit"].startswith("2026-11-16T01:5")
    assert smc["best"] is not None
    assert smc["observable"] > 6 * 3600
    assert len(smc["altitude"]) == len(smc["horizon"]) == len(body["times"])
    assert (m31["above_horizon"], m31["best"]) == (0, None)


@pytest.mark.parametrize(
    "params",
    [
        {"target": "NGC 292"},
        {"target": "25,10"},
        {"target": "1,-91"},
        {"target": "1,2", "min_altitude": "95"},
        {"target": "1,2", "date": "1800-01-01"},
        {},
    ],
)
def test_visibility_refuses_bad_requests(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/api/sky/visibility", params=params).status_code == 422


def test_sky_needs_a_site(config_dir: Path) -> None:
    profiles = ProfileStore(config_dir)
    profiles.put("bare", Profile(name="Bare"))
    profiles.active = "bare"
    with TestClient(create_app(Settings(indi_host="127.0.0.1", indi_port=9))) as client:
        pair_owner(client)
        assert client.get("/api/sky/tonight").status_code == 409


def test_observers_may_read_the_sky(client: TestClient) -> None:
    client.put("/api/auth/observer", json={"enabled": True})
    client.cookies.clear()
    assert client.get("/api/sky/tonight", params={"date": "2026-11-15"}).status_code == 200
    assert client.get("/api/profiles").status_code == 401
