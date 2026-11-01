# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A USB GPS through gpsd (ADR 0029), with a fake gpsd and a fake equipment service."""

import json
from collections.abc import Callable
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
from nocs.equipment.profiles import Profile, Site
from nocs.services import gps as gps_module
from nocs.services.gps import GpsService, NoFixError
from nocs.state import StateStore

DIAGUITAS = Site(name="Diaguitas", latitude=-30.0277, longitude=-70.6733, elevation=700)


class FakeEquipment:
    def __init__(self, site: Site | None) -> None:
        self.active_profile: Profile | None = Profile(name="AM5", site=site)
        self.listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self.listeners.append(listener)
        return lambda: None

    def set_site(self, site: Site) -> None:
        assert self.active_profile is not None
        self.active_profile = self.active_profile.model_copy(update={"site": site})
        for listener in self.listeners:
            listener()


def tpv(mode: int, lat: float = -30.02772, lon: float = -70.67331, alt: float = 702.4) -> bytes:
    report = {"class": "TPV", "mode": mode, "time": "2026-11-01T03:04:05.000Z"}
    if mode >= 2:
        report |= {"lat": lat, "lon": lon}
    if mode == 3:
        report |= {"altMSL": alt, "altHAE": alt + 30}
    return json.dumps(report).encode() + b"\n"


def make(site: Site | None = DIAGUITAS) -> tuple[GpsService, FakeEquipment, StateStore]:
    store = StateStore()
    equipment = FakeEquipment(site)
    service = GpsService(store, equipment, "localhost", 0)  # pyright: ignore[reportArgumentType]
    return service, equipment, store


def state(store: StateStore) -> GpsState:
    return GpsState.model_validate(store.get(("gps",)))


def test_a_3d_fix_near_the_profile_site() -> None:
    service, _, store = make()
    service.on_message(b'{"class":"VERSION","release":"3.25"}\n')
    assert state(store).fix == "none"
    service.on_message(tpv(3))
    gps = state(store)
    assert (gps.fix, gps.latitude, gps.longitude, gps.elevation) == ("3d", -30.0277, -70.6733, 702)
    assert gps.site_differs is False
    assert gps.time == "2026-11-01T03:04:05.000Z"


def test_far_from_the_site_or_without_one_it_is_offered() -> None:
    service, _, store = make()
    service.on_message(tpv(3, lat=-33.45, lon=-70.66))
    assert state(store).site_differs is True
    service, _, store = make(site=None)
    service.on_message(tpv(3))
    assert state(store).site_differs is True


def test_a_2d_fix_has_no_elevation_and_offers_nothing() -> None:
    service, _, store = make()
    service.on_message(tpv(2))
    gps = state(store)
    assert (gps.fix, gps.elevation, gps.site_differs) == ("2d", None, None)
    with pytest.raises(NoFixError):
        service.site()


def test_a_wandering_fix_is_published_at_most_every_10_s(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(gps_module.time, "monotonic", lambda: now[0])
    service, _, store = make()
    service.on_message(tpv(3))
    version = store.version
    service.on_message(tpv(3, lat=-30.02790))
    assert store.version == version
    now[0] += 11
    service.on_message(tpv(3, lat=-30.02791))
    assert store.version == version + 1
    assert state(store).latitude == -30.0279


def test_apply_the_site_keeps_its_name() -> None:
    service, equipment, store = make()
    service.on_message(tpv(3, lat=-30.1, lon=-70.5, alt=812))
    site = service.apply_site()
    assert site == Site(name="Diaguitas", latitude=-30.1, longitude=-70.5, elevation=812)
    assert equipment.active_profile is not None
    assert equipment.active_profile.site == site
    assert state(store).site_differs is False


async def test_follows_gpsd(monkeypatch: pytest.MonkeyPatch) -> None:
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
    service = GpsService(store, FakeEquipment(DIAGUITAS), "127.0.0.1", port)  # pyright: ignore[reportArgumentType]
    async with anyio.create_task_group() as tg:
        tg.start_soon(listener.serve, gpsd)
        tg.start_soon(service.run)
        with anyio.fail_after(5):
            while state(store).fix != "3d":  # noqa: ASYNC110
                await anyio.sleep(0.01)
        assert state(store).connected is True
        assert received[0].startswith(b"?WATCH=")
        tg.cancel_scope.cancel()


async def test_without_gpsd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gps_module, "RETRY", 0.05)
    store = StateStore()
    service = GpsService(store, FakeEquipment(DIAGUITAS), "127.0.0.1", 9)  # pyright: ignore[reportArgumentType]
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
