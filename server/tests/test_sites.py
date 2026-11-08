# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Saved sites and the box's active one (ADR 0038)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import SitesState
from nocs.config import Settings
from nocs.jobs import JobManager, ResourceBusyError
from nocs.sites import HorizonPoint, Site, SiteError, SiteService, SiteStore, distance
from nocs.state import StateStore

DIAGUITAS = Site(name="Diaguitas", latitude=-30.0277, longitude=-70.6733, elevation=700)
VICUNA = Site(name="Vicuña", latitude=-30.0319, longitude=-70.7081, elevation=650)


def state(store: StateStore) -> SitesState:
    return SitesState.model_validate(store.get(("sites",)))


def test_saved_and_active_sites_persist(tmp_path: Path) -> None:
    store = StateStore()
    sites = SiteService(store, SiteStore(tmp_path))
    assert (sites.active, state(store)) == (None, SitesState(active=None, saved={}))
    diaguitas = sites.add(DIAGUITAS)
    vicuna = sites.add(VICUNA, activate=True)
    assert diaguitas != vicuna
    assert (sites.active_id, sites.active) == (vicuna, VICUNA)
    assert state(store) == SitesState(active=vicuna, saved={diaguitas: DIAGUITAS, vicuna: VICUNA})

    again = SiteService(StateStore(), SiteStore(tmp_path))
    assert (again.active_id, again.saved()) == (vicuna, {diaguitas: DIAGUITAS, vicuna: VICUNA})


def test_listeners_follow_the_active_site(tmp_path: Path) -> None:
    sites = SiteService(StateStore(), SiteStore(tmp_path))
    active: list[Site | None] = []
    saved: list[int] = []
    sites.add_listener(lambda: active.append(sites.active))
    sites.add_listener(lambda: saved.append(len(sites.saved())), saved=True)
    diaguitas = sites.add(DIAGUITAS)
    assert (active, saved) == ([], [1])
    sites.activate(diaguitas)
    sites.activate(diaguitas)  # already active: nothing changes
    moved = DIAGUITAS.model_copy(update={"elevation": 720})
    sites.put(diaguitas, moved)
    vicuna = sites.add(VICUNA)
    sites.put(vicuna, VICUNA.model_copy(update={"name": "Vicuña town"}))
    sites.delete(diaguitas)
    assert active == [DIAGUITAS, moved, None]
    assert saved == [1, 1, 1, 2, 2, 1]
    assert sites.active is None
    assert list(sites.saved()) == [vicuna]


def test_the_active_site_waits_while_a_job_holds_the_mount(tmp_path: Path) -> None:
    jobs = JobManager(StateStore())
    sites = SiteService(StateStore(), SiteStore(tmp_path), lambda: jobs.check_free(["mount"]))
    diaguitas = sites.add(DIAGUITAS, activate=True)
    vicuna = sites.add(VICUNA)
    token = jobs.reserve("goto", ["mount"])
    for change in (
        lambda: sites.activate(vicuna),
        lambda: sites.activate(None),
        lambda: sites.put(diaguitas, VICUNA),
        lambda: sites.delete(diaguitas),
        lambda: sites.add(VICUNA, activate=True),
    ):
        with pytest.raises(ResourceBusyError):
            change()
    sites.put(vicuna, VICUNA.model_copy(update={"elevation": 600}))  # not the active one
    sites.delete(vicuna)
    jobs.release(token)
    sites.activate(None)
    assert sites.active is None


def test_unknown_sites(tmp_path: Path) -> None:
    sites = SiteService(StateStore(), SiteStore(tmp_path))
    for change in (
        lambda: sites.activate("nowhere"),
        lambda: sites.put("nowhere", DIAGUITAS),
        lambda: sites.delete("nowhere"),
    ):
        with pytest.raises(SiteError):
            change()


def test_an_unreadable_file_or_a_lost_active_site(tmp_path: Path) -> None:
    (tmp_path / "sites.json").write_text("{not json")
    assert SiteService(StateStore(), SiteStore(tmp_path)).saved() == {}
    (tmp_path / "sites.json").write_text('{"active": "gone", "sites": {}}')
    assert SiteService(StateStore(), SiteStore(tmp_path)).active_id is None


def test_nearest_within_500_m(tmp_path: Path) -> None:
    sites = SiteService(StateStore(), SiteStore(tmp_path))
    diaguitas = sites.add(DIAGUITAS)
    vicuna = sites.add(VICUNA)
    assert distance(DIAGUITAS, VICUNA.latitude, VICUNA.longitude) == pytest.approx(3380, abs=20)
    assert sites.nearest(DIAGUITAS.latitude, DIAGUITAS.longitude) == diaguitas
    assert sites.nearest(-30.0300, -70.7050) == vicuna  # ~400 m away
    assert sites.nearest(-30.0300, -70.6900) is None  # ~1.6 km from either
    # Across the antimeridian, too.
    pacific = sites.add(Site(name="Pacific", latitude=0, longitude=179.999))
    assert sites.nearest(0, -179.999) == pacific


# -- API ------------------------------------------------------------------------


@pytest.fixture
def client(config_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(indi_host="127.0.0.1", indi_port=9))) as client:
        pair_owner(client)
        yield client


def sites_state(client: TestClient) -> SitesState:
    return SitesState.model_validate(client.get("/api/state").json()["state"]["sites"])


def test_sites_api(client: TestClient) -> None:
    hill = [HorizonPoint(azimuth=0, altitude=20)]
    response = client.post(
        "/api/sites", json={**DIAGUITAS.model_dump(), "horizon": [{"azimuth": 0, "altitude": 20}]}
    )
    assert response.status_code == 201, response.text
    diaguitas = response.json()["id"]
    assert sites_state(client) == SitesState(
        active=None, saved={diaguitas: DIAGUITAS.model_copy(update={"horizon": hill})}
    )
    assert client.put("/api/sites/active", json={"id": diaguitas}).status_code == 204
    assert client.get("/api/sky/tonight").status_code == 200
    response = client.put(f"/api/sites/{diaguitas}", json=VICUNA.model_dump())
    assert response.status_code == 204
    assert sites_state(client).saved[diaguitas] == VICUNA
    assert client.put("/api/sites/active", json={"id": None}).status_code == 204
    assert client.get("/api/sky/tonight").status_code == 409
    assert client.delete(f"/api/sites/{diaguitas}").status_code == 204
    assert sites_state(client) == SitesState(active=None, saved={})


def test_sites_api_refusals(client: TestClient) -> None:
    assert client.put("/api/sites/active", json={"id": "nowhere"}).status_code == 404
    assert client.put("/api/sites/nowhere", json=DIAGUITAS.model_dump()).status_code == 404
    assert client.delete("/api/sites/nowhere").status_code == 404
    bad = {**DIAGUITAS.model_dump(), "latitude": 91}
    assert client.post("/api/sites", json=bad).status_code == 422


def test_observers_see_the_sites_but_cannot_change_them(client: TestClient) -> None:
    client.post("/api/sites", json=DIAGUITAS.model_dump())
    client.put("/api/auth/observer", json={"enabled": True})
    client.cookies.clear()
    assert client.post("/api/sites", json=VICUNA.model_dump()).status_code == 401
    assert len(sites_state(client).saved) == 1
