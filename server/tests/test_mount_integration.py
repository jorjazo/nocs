# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Mount control through the API, against the telescope simulator (ADR 0015)."""

import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings
from nocs.mount.coords import j2000_to_jnow

pytestmark = pytest.mark.indi

SITE = {"name": "Diaguitas", "latitude": -30.03, "longitude": -70.65, "elevation": 1100}
PROFILE = {
    "name": "Mount only",
    "devices": {"mount": {"driver": "indi_simulator_telescope"}},
    "site": SITE,
}


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def mount(api: TestClient) -> dict[str, Any]:
    return state(api)["mount"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {k: current.get(k) for k in ("mount", "jobs")}
        time.sleep(0.05)


def finished(job_id: str) -> Callable[[dict[str, Any]], bool]:
    return lambda s: s["jobs"][job_id]["state"] != "running"


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    value = os.environ.get("NOCS_TEST_INDI")
    if not value:
        pytest.skip("NOCS_TEST_INDI not set")
    host, _, port = value.rpartition(":")
    settings = Settings(
        indi_host=host,
        indi_port=int(port),
        config_dir=tmp_path_factory.mktemp("config"),
        data_dir=tmp_path_factory.mktemp("data"),
    )
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        assert client.put("/api/profiles/mount", json=PROFILE).status_code == 204
        assert client.post("/api/equipment/connect", json={"profile": "mount"}).status_code == 202
        wait(client, lambda s: s.get("mount") is not None)
        if mount(client)["parked"]:
            assert client.post("/api/mount/unpark").status_code == 204
        try:
            yield client
        finally:
            client.post("/api/mount/abort")
            client.post("/api/mount/unpark")


def test_state(api: TestClient) -> None:
    current = state(api)
    AppState.model_validate(current)
    m = current["mount"]
    assert m["device"] == "Telescope Simulator"
    assert m["slew_rates"]
    assert m["can_home"]
    assert m["moving"] == {"ns": None, "we": None}
    assert current["clock"]["offset"] is None
    # No client has reported its clock yet: no alt/az of our own.
    assert (m["alt"], m["az"]) == (None, None)


def test_site_is_sent_on_connect_and_go_to_waits_for_the_time(api: TestClient) -> None:
    wait(api, lambda s: s["mount"]["site_sent"], timeout=5)
    m = mount(api)
    assert (m["site_check"], m["time_sent"]) == ("same", False)
    response = api.post("/api/mount/goto", json={"frame": "jnow", "ra": 1, "dec": -60})
    assert response.status_code == 409
    assert "has not received the time" in response.json()["detail"]


def test_clock_report_sets_the_mount_time(api: TestClient) -> None:
    response = api.post("/api/clock", json={"utc": datetime.now(UTC).isoformat(), "utc_offset": -3})
    assert response.status_code == 200
    assert response.json()["corrected"] is False
    wait(api, lambda s: s["mount"]["time_sent"], timeout=5)
    assert _age(mount(api)["time"]) < 5
    assert mount(api)["alt"] is not None


def test_site_from_the_profile(api: TestClient) -> None:
    assert api.put("/api/mount/site", json={}).status_code == 204
    wait(api, lambda s: s["mount"]["site_check"] == "same")
    site = mount(api)["site"]
    assert site["latitude"] == pytest.approx(SITE["latitude"])
    assert site["longitude"] == pytest.approx(SITE["longitude"])


def test_goto_below_the_horizon_is_refused(api: TestClient) -> None:
    # Dec +80 never rises at latitude -30.
    response = api.post("/api/mount/goto", json={"frame": "j2000", "ra": 1.0, "dec": 80.0})
    assert response.status_code == 409
    assert "below the horizon" in response.json()["detail"]


def test_goto_zenith_stops_tracking(api: TestClient) -> None:
    response = api.post("/api/mount/goto", json={"frame": "altaz", "alt": 90, "az": 0})
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    wait(api, finished(job))
    assert state(api)["jobs"][job]["state"] == "succeeded"
    m = mount(api)
    assert not m["tracking"]
    assert m["alt"] == pytest.approx(90, abs=0.2)
    assert m["dec"] == pytest.approx(SITE["latitude"], abs=0.1)


def test_goto_j2000(api: TestClient) -> None:
    # A short slew from the zenith, in declination only: crossing the meridian there
    # would flip the simulated mount to the other side of the pier.
    current = mount(api)
    ra, dec = current["ra_j2000"], current["dec_j2000"] - 2
    response = api.post(
        "/api/mount/goto", json={"frame": "j2000", "ra": ra, "dec": dec, "force": True}
    )
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    wait(api, finished(job))
    current = state(api)
    assert current["jobs"][job]["state"] == "succeeded", current["jobs"][job]
    m = current["mount"]
    assert m["ra_j2000"] == pytest.approx(ra, abs=0.01)
    assert m["dec_j2000"] == pytest.approx(dec, abs=0.1)
    jnow = j2000_to_jnow(ra, dec, datetime.now(UTC))
    assert m["dec"] == pytest.approx(jnow.dec, abs=0.1)
    assert m["tracking"]


def test_cancelling_a_goto_aborts_it(api: TestClient) -> None:
    current = mount(api)
    ra = (current["ra_j2000"] + 4) % 24
    response = api.post(
        "/api/mount/goto", json={"frame": "jnow", "ra": ra, "dec": -20.0, "force": True}
    )
    job = response.json()["job"]
    wait(api, lambda s: s["mount"]["slewing"])
    assert api.post("/api/mount/goto", json={"frame": "jnow", "ra": 1, "dec": 0}).status_code == 409
    assert api.post(f"/api/jobs/{job}/cancel").status_code == 202
    wait(api, finished(job))
    assert state(api)["jobs"][job]["state"] == "cancelled"
    wait(api, lambda s: not s["mount"]["slewing"], timeout=5)
    assert mount(api)["ra"] != pytest.approx(ra, abs=0.05)


def test_abort_stops_a_goto(api: TestClient) -> None:
    current = mount(api)
    ra = (current["ra"] + 4) % 24
    response = api.post(
        "/api/mount/goto", json={"frame": "jnow", "ra": ra, "dec": -30.0, "force": True}
    )
    job = response.json()["job"]
    wait(api, lambda s: s["mount"]["slewing"])
    assert api.post("/api/mount/abort").status_code == 202
    wait(api, finished(job), timeout=5)
    assert state(api)["jobs"][job]["state"] == "cancelled"
    wait(api, lambda s: not s["mount"]["slewing"], timeout=5)


def test_tracking(api: TestClient) -> None:
    # Right after test_abort_stops_a_goto: the simulator's switch may still say on.
    assert api.put("/api/mount/tracking", json={"on": True}).status_code == 204
    assert mount(api)["tracking"]
    time.sleep(1.5)  # past the driver's next poll, when it syncs the switch
    assert mount(api)["tracking"]
    assert api.put("/api/mount/tracking", json={"mode": "lunar"}).status_code == 204
    assert mount(api)["track_mode"] == "lunar"
    assert api.put("/api/mount/tracking", json={"mode": "sidereal"}).status_code == 204
    assert api.put("/api/mount/tracking", json={"mode": "warp"}).status_code == 422


def hold(ws: Any, ns: str | None = None, we: str | None = None, rate: str | None = None) -> None:
    ws.send_json({"ns": ns, "we": we, "rate": rate})


def test_pad_moves_while_held(api: TestClient) -> None:
    rate = mount(api)["slew_rates"][0]
    with api.websocket_connect("/api/mount/pad") as ws:
        hold(ws, ns="north", rate=rate)
        status = ws.receive_json()
        assert status["moving"] == {"ns": "north", "we": None}, status
        assert (status["rate"], status["latched"]) == (rate, False)
        assert mount(api)["moved_by"] == "tests"
        # Other commands wait for the pad.
        assert api.post("/api/mount/park").status_code == 409
        for _ in range(4):
            time.sleep(0.25)
            hold(ws, ns="north", rate=rate)
            assert ws.receive_json()["moving"]["ns"] == "north"
        assert mount(api)["moving"]["ns"] == "north"
        hold(ws)
        assert ws.receive_json()["moving"] == {"ns": None, "we": None}
    wait(api, lambda s: s["mount"]["moving"] == {"ns": None, "we": None}, timeout=2)
    assert mount(api)["moved_by"] is None


def test_dead_man_stops_a_silent_pad(api: TestClient) -> None:
    with api.websocket_connect("/api/mount/pad") as ws:
        hold(ws, we="east")
        assert ws.receive_json()["moving"]["we"] == "east"
        started = time.monotonic()
        # The phone goes silent with the button down; the socket stays open.
        status = ws.receive_json()
        elapsed = time.monotonic() - started
        assert status["latched"], status
        assert status["moving"] == {"ns": None, "we": None}
        assert 0.8 < elapsed < 1.6
        assert mount(api)["moving"]["we"] is None
        # Back again, still holding: nothing moves until it lets go.
        hold(ws, we="east")
        assert ws.receive_json()["latched"]
        assert mount(api)["moving"]["we"] is None
        hold(ws)
        assert not ws.receive_json()["latched"]


def test_closing_the_pad_stops(api: TestClient) -> None:
    with api.websocket_connect("/api/mount/pad") as ws:
        hold(ws, ns="south", we="west")
        assert ws.receive_json()["moving"] == {"ns": "south", "we": "west"}
    wait(api, lambda s: s["mount"]["moving"] == {"ns": None, "we": None}, timeout=2)


def simulator(api: TestClient, name: str, values: dict[str, bool]) -> None:
    path = f"/api/indi/devices/Telescope Simulator/properties/{name}"
    assert api.post(path, json={"values": values}).status_code == 202


def test_park_home_and_unpark(api: TestClient) -> None:
    # Park and home where the mount is: the simulator's own positions are a minute away.
    simulator(api, "TELESCOPE_PARK_OPTION", {"PARK_CURRENT": True})
    simulator(api, "TELESCOPE_HOME", {"SET": True})
    time.sleep(0.5)
    response = api.post("/api/mount/park")
    assert response.status_code == 202
    job = response.json()["job"]
    wait(api, finished(job))
    assert state(api)["jobs"][job]["state"] == "succeeded"
    assert mount(api)["parked"]
    assert api.post("/api/mount/home").status_code == 422  # parked
    with api.websocket_connect("/api/mount/pad") as ws:
        hold(ws, ns="north")
        status = ws.receive_json()
        assert status["latched"]
        assert "parked" in status["message"]
    assert api.post("/api/mount/unpark").status_code == 204
    assert not mount(api)["parked"]
    response = api.post("/api/mount/home")
    assert response.status_code == 202
    job = response.json()["job"]
    wait(api, finished(job))
    assert state(api)["jobs"][job]["state"] == "succeeded", state(api)["jobs"][job]


def _age(text: str) -> float:
    return abs((datetime.now(UTC) - datetime.fromisoformat(text)).total_seconds())
