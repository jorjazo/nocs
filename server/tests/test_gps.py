# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A USB GPS through gpsd (ADR 0029) and the saved sites it is at (ADR 0038), with a
fake gpsd."""

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from anyio.abc import SocketStream
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import GpsState
from nocs.config import Settings
from nocs.services import gps as gps_module
from nocs.services.gps import GpsService, NoFixError
from nocs.sites import Site, SiteService, SiteStore
from nocs.state import StateStore

DIAGUITAS = Site(name="Diaguitas", latitude=-30.0277, longitude=-70.6733, elevation=700)


def tpv(mode: int, lat: float = -30.02772, lon: float = -70.67331, alt: float = 702.4) -> bytes:
    report = {"class": "TPV", "mode": mode, "time": "2026-11-01T03:04:05.000Z"}
    if mode >= 2:
        report |= {"lat": lat, "lon": lon}
    if mode == 3:
        report |= {"altMSL": alt, "altHAE": alt + 30}
    return json.dumps(report).encode() + b"\n"


def make(
    tmp_path: Path, site: Site | None = DIAGUITAS
) -> tuple[GpsService, SiteService, StateStore]:
    store = StateStore()
    sites = SiteService(store, SiteStore(tmp_path))
    if site is not None:
        sites.add(site, activate=True)
    return GpsService(store, sites, "localhost", 0), sites, store


def state(store: StateStore) -> GpsState:
    return GpsState.model_validate(store.get(("gps",)))


def test_a_3d_fix_at_the_active_site(tmp_path: Path) -> None:
    service, sites, store = make(tmp_path)
    service.on_message(b'{"class":"VERSION","release":"3.25"}\n')
    assert state(store).fix == "none"
    service.on_message(tpv(3))
    gps = state(store)
    assert (gps.fix, gps.latitude, gps.longitude, gps.elevation) == ("3d", -30.0277, -70.6733, 702)
    assert gps.site == sites.active_id
    assert gps.time == "2026-11-01T03:04:05.000Z"


def test_within_500_m_of_a_saved_site(tmp_path: Path) -> None:
    service, sites, store = make(tmp_path)
    # About 440 m south of Diaguitas, then about 560 m.
    service.on_message(tpv(3, lat=-30.0317))
    assert state(store).site == sites.active_id
    service.on_message(tpv(3, lat=-30.0327))
    assert state(store).site is None


def test_the_nearest_saved_site(tmp_path: Path) -> None:
    service, sites, store = make(tmp_path)
    near = sites.add(Site(name="Hill", latitude=-30.0300, longitude=-70.6733))
    service.on_message(tpv(3, lat=-30.0295))
    assert state(store).site == near
    sites.delete(near)  # the GPS follows the saved sites, not only the active one
    assert state(store).site == sites.active_id


def test_a_2d_fix_has_no_elevation_and_offers_nothing(tmp_path: Path) -> None:
    service, _, store = make(tmp_path)
    service.on_message(tpv(2))
    gps = state(store)
    assert (gps.fix, gps.elevation, gps.site) == ("2d", None, None)
    with pytest.raises(NoFixError):
        service.site()


def test_a_wandering_fix_is_published_at_most_every_10_s(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    now = [1000.0]
    monkeypatch.setattr(gps_module.time, "monotonic", lambda: now[0])
    service, _, store = make(tmp_path)
    service.on_message(tpv(3))
    version = store.version
    service.on_message(tpv(3, lat=-30.02790))
    assert store.version == version
    now[0] += 11
    service.on_message(tpv(3, lat=-30.02791))
    assert store.version == version + 1
    assert state(store).latitude == -30.0279


def test_use_a_saved_site(tmp_path: Path) -> None:
    service, sites, _ = make(tmp_path, site=None)
    diaguitas = sites.add(DIAGUITAS)
    service.on_message(tpv(3))
    assert sites.active_id is None
    assert service.use_site("ignored") == diaguitas
    assert (sites.active_id, sites.active) == (diaguitas, DIAGUITAS)  # kept as it was saved
    assert len(sites.saved()) == 1


def test_save_a_new_site(tmp_path: Path) -> None:
    service, sites, store = make(tmp_path)
    service.on_message(tpv(3, lat=-30.1, lon=-70.5, alt=812.4))
    site_id = service.use_site(" Vicuña ")
    assert sites.active_id == site_id
    assert sites.active == Site(name="Vicuña", latitude=-30.1, longitude=-70.5, elevation=812)
    assert len(sites.saved()) == 2
    assert state(store).site == site_id
    service.on_message(tpv(3, lat=-31, lon=-71))
    assert sites.get(service.use_site()).name == "GPS"


async def test_follows_gpsd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gps_module, "RETRY", 0.05)
    received: list[bytes] = []

    async def gpsd(stream: SocketStream) -> None:
        async with stream:
            received.append(await stream.receive())
            await stream.send(b'{"class":"VERSION","release":"3.25"}\n' + tpv(3))
            await anyio.sleep(1)

    listener = await anyio.create_tcp_listener(local_host="127.0.0.1")
    port: Any = listener.extra(anyio.abc.SocketAttribute.local_port)
    store = StateStore()
    service = GpsService(store, SiteService(store, SiteStore(tmp_path)), "127.0.0.1", port)
    async with anyio.create_task_group() as tg:
        tg.start_soon(listener.serve, gpsd)
        tg.start_soon(service.run)
        with anyio.fail_after(5):
            while state(store).fix != "3d":  # noqa: ASYNC110
                await anyio.sleep(0.01)
        assert state(store).connected is True
        assert received[0].startswith(b"?WATCH=")
        tg.cancel_scope.cancel()


async def test_without_gpsd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gps_module, "RETRY", 0.05)
    store = StateStore()
    service = GpsService(store, SiteService(store, SiteStore(tmp_path)), "127.0.0.1", 9)
    with anyio.move_on_after(0.2):
        await service.run()
    assert (state(store).connected, state(store).fix) == (False, "none")


def test_the_api_refuses_a_site_without_a_fix(tmp_path: Path) -> None:
    settings = Settings(
        indi_host="127.0.0.1",
        indi_port=9,
        gpsd_port=9,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        system_socket=tmp_path / "missing.sock",
    )
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        response = client.post("/api/gps/site")
        assert response.status_code == 409
        assert client.get("/api/state").json()["state"]["gps"]["connected"] is False
