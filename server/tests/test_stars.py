# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The framing chart's data: the Tycho-2 subset, objects around a point, the API (ADR 0020)."""

import math
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import SkyChart
from nocs.config import Settings
from nocs.targets import TargetCatalog, bundled_catalog
from nocs.targets.catalog import Source, separation
from nocs.targets.stars import Star, StarCatalog, bundled_stars, encode
from nocs.targets.tycho2 import johnson_v, parse_main, parse_supplement, select

# Real records: a normal star, one without a mean position, Sirius (Hipparcos, in
# supplement 1, Hp instead of VT) and a Tycho-1 star without proper motion.
MAIN = (
    "0001 00013 1| |  1.12558209|  2.26739400|   27.7|   -0.5|  9| 12| 1.2| 1.2|1990.76|1989.25|"
    " 8|1.0|0.8|1.0|0.7|10.488|0.038| 8.670|0.015|999|T|         |  1.12551889|  2.26739556|1.81|"
    "1.52|  9.3| 12.7| |-0.2"
)
NO_MEAN = (
    "0001 00041 1|X|            |            |       |       |   |   |    |    |       |       |"
    "  |   |   |   |   |13.035|0.320|12.235|0.220|999| |         |  1.80874194|  2.31573611|1.75|"
    "1.77|112.2|148.2| | 0.0"
)
SIRIUS = (
    "5949 02777 1|H|101.28854105|-16.71314306| -546.0|-1223.1|  1.2|  1.0|  1.3|  1.2|H|      |"
    "     |-1.088|0.002|999| | 32349 "
)
TYCHO1 = (
    "0002 00580 1|T|003.03708871|+01.57351477|       |       | 42.9| 39.5|     |     | |11.688|"
    "0.122|11.171|0.121|999|T|       "
)


def test_tycho2_records_become_j2000_stars() -> None:
    star = parse_main(MAIN)
    assert star.ra == pytest.approx(1.12558209 / 15)
    assert star.dec == pytest.approx(2.26739400)
    assert star.magnitude == pytest.approx(8.670 - 0.090 * (10.488 - 8.670))

    star = parse_main(NO_MEAN)  # the observed position instead
    assert (star.ra * 15, star.dec) == pytest.approx((1.80874194, 2.31573611))

    sirius = parse_supplement(SIRIUS)
    assert sirius.magnitude == pytest.approx(-1.088)
    # Its 1.2″/yr proper motion over 8.75 years, to the J2000 position SIMBAD gives.
    assert separation(sirius.ra, sirius.dec, 6.752477, -16.716116) * 3600 < 0.5
    assert parse_supplement(TYCHO1).magnitude == pytest.approx(11.171 - 0.090 * (11.688 - 11.171))

    assert johnson_v(None, 9.0) == 9.0
    assert johnson_v(9.5, None) == 9.5
    with pytest.raises(ValueError, match="short"):
        parse_main("0001 00013 1| |")


def test_selection_keeps_bright_stars_in_declination_order() -> None:
    stars = [Star(1, 10, 9.5), Star(2, -5, 10.5), Star(3, -20, 4.0)]
    assert select(stars, 10.0) == [Star(3, -20, 4.0), Star(1, 10, 9.5)]


SOURCE = Source("Tycho-2", "test", "https://example.org", "CC BY-NC 3.0 IGO", "", "Credit: ESA")


def test_the_star_file_round_trips_to_its_precision() -> None:
    stars = [
        Star(23.999999, -89.99, -1.46),
        Star(0.0, 0.0, 10.0),
        Star(12.3456789, 45.678912, 7.33),
    ]
    catalog = StarCatalog.from_bytes(encode(select(stars, 10), [SOURCE], 10))
    assert len(catalog) == 3
    assert catalog.sources == (SOURCE,)
    assert catalog.magnitude_limit == 10
    assert list(catalog.dec) == pytest.approx([-89.99, 0.0, 45.678912], abs=0.5e-4)
    # 24h wraps to 0h.
    assert list(catalog.ra) == pytest.approx([0.0, 0.0, 12.3456789], abs=0.5e-4 / 15)
    assert list(catalog.magnitude) == pytest.approx([-1.45, 10.0, 7.35])
    assert encode(stars, [SOURCE], 10) == encode(stars, [SOURCE], 10)


def _grid() -> StarCatalog:
    """A star every 0.5° in RA and Dec, magnitude growing with RA."""
    stars = [
        Star(ra / 15, dec, 2 + (ra % 10))
        for ra in [i * 0.5 for i in range(720)]
        for dec in [j * 0.5 for j in range(-179, 180)]
    ]
    return StarCatalog.from_stars(stars)


def test_near_finds_stars_inside_the_circle_across_0h_and_the_pole() -> None:
    catalog = _grid()
    field = catalog.near(0.0, 0.0, 1.0)
    assert len(field) > 0
    distances = [separation(0, 0, r, d) for r, d in zip(field.ra, field.dec, strict=True)]
    assert max(distances) <= 1.0 + 1e-9
    # Around 0h, stars at 359.5° are found as well as at 0.5°.
    assert any(r > 23 for r in field.ra)
    assert any(0 < r < 1 for r in field.ra)
    # ~π r² / 0.25 deg² per star.
    assert len(field) == pytest.approx(math.pi / 0.25, rel=0.2)

    polar = catalog.near(5.0, -89.0, 1.6)
    assert len({round(r, 3) for r in polar.ra}) == 720  # every RA on the -89.5° ring
    distances = [separation(5, -89, r, d) for r, d in zip(polar.ra, polar.dec, strict=True)]
    assert max(distances) <= 1.6 + 1e-9


def test_near_keeps_the_brightest_first_and_respects_magnitude_and_limit() -> None:
    catalog = _grid()
    field = catalog.near(1.0, 30.0, 3.0, magnitude=6.0)
    assert len(field) > 0
    assert max(field.magnitude) <= 6.0
    assert list(field.magnitude) == sorted(field.magnitude)
    assert not field.truncated

    everything = catalog.near(1.0, 30.0, 3.0)
    limited = catalog.near(1.0, 30.0, 3.0, limit=10)
    assert limited.truncated
    assert len(limited) == 10
    assert list(limited.magnitude) == sorted(everything.magnitude)[:10]


def test_the_bundled_stars_cover_the_exit_targets() -> None:
    stars = bundled_stars()
    assert len(stars) > 300_000
    assert stars.magnitude_limit == 10.0
    assert [s.name for s in stars.sources] == ["Tycho-2"]
    # The brightest star, from supplement 1, where the Hipparcos stars missing from Tycho-2 are.
    sirius = stars.near(6.7525, -16.716, 0.05)
    assert len(sirius) == 1
    assert sirius.magnitude[0] < -1
    # Around NGC 292 (the SMC) and NGC 253, as the chart asks for them.
    assert 50 < len(stars.near(0.8768, -72.83, 2.5)) < 500
    assert 5 < len(stars.near(0.7928, -25.29, 1.0)) < 100


@pytest.fixture(scope="module")
def catalog() -> TargetCatalog:
    return bundled_catalog()


def test_objects_near_a_point_include_large_ones_whose_centre_is_outside(
    catalog: TargetCatalog,
) -> None:
    near_253 = {t.id for t in catalog.near(0.7928, -25.29, 1.0)}
    assert "NGC 253" in near_253
    assert "NGC 247" not in near_253  # 4.5° north
    # A point 2° off the SMC's centre, inside its 5° by 3° extent.
    assert "NGC 292" in {t.id for t in catalog.near(0.95, -70.9, 0.2)}
    assert "NGC 292" not in {t.id for t in catalog.near(0.95, -66.0, 0.2)}


# -- API --------------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(indi_host="127.0.0.1", indi_port=9)  # nothing listens there
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        yield client


def test_api_draws_the_chart_around_ngc_253(client: TestClient) -> None:
    response = client.get("/api/targets/chart", params={"ra": 0.7928, "dec": -25.29, "radius": 2})
    assert response.status_code == 200
    chart = SkyChart.model_validate(response.json())
    assert chart.magnitude == 10.0  # the file's limit
    assert chart.star_catalog
    assert 20 < len(chart.stars) < 400
    assert not chart.truncated
    assert all(len(s) == 3 for s in chart.stars)
    assert [s[2] for s in chart.stars] == sorted(s[2] for s in chart.stars)
    galaxy = next(o for o in chart.objects if o.id == "NGC 253")
    assert (galaxy.major_axis, galaxy.position_angle) == (pytest.approx(27, abs=1), 53)

    faint = client.get(
        "/api/targets/chart",
        params={"ra": 0.7928, "dec": -25.29, "radius": 2, "magnitude": 8, "limit": 5},
    ).json()
    assert len(faint["stars"]) == 5
    assert faint["truncated"]
    assert faint["magnitude"] == 8

    smc = client.get(
        "/api/targets/chart", params={"ra": 0.8768, "dec": -72.83, "radius": 10, "objects": 20}
    ).json()["objects"]
    assert len(smc) == 20
    assert smc[0]["id"] == "NGC 292"  # the brightest object there
    magnitudes = [o["magnitude"] if o["magnitude"] is not None else 99 for o in smc]
    assert magnitudes == sorted(magnitudes)

    for bad in [{"ra": 24}, {"dec": -91}, {"radius": 0}, {"radius": 31}]:
        params = {"ra": 1, "dec": 0, "radius": 1} | bad
        assert client.get("/api/targets/chart", params=params).status_code == 422, bad


def test_observers_may_draw_the_chart(client: TestClient) -> None:
    assert client.put("/api/auth/observer", json={"enabled": True}).status_code == 204
    client.cookies.clear()
    response = client.get("/api/targets/chart", params={"ra": 0.8768, "dec": -72.83, "radius": 3})
    assert response.status_code == 200
    assert "NGC 292" in {o["id"] for o in response.json()["objects"]}
