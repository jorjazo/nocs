# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Live stacking of the CCD simulator's frames (GSC stars) through the API."""

import json
import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner
from sites import use_site

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings

pytestmark = pytest.mark.indi

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
SITE = {"name": "Lab", "latitude": -30.2, "longitude": -70.7, "elevation": 2400}
DEC = -45.0
"""A field well above the horizon of the site, away from the pole (as the solving tests)."""
NUDGE = 40 / 3600
"""Degrees the mount moves between frames: a dither of a few pixels."""


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {k: current.get(k) for k in ("stack", "jobs")}
        time.sleep(0.1)


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
    devices = {k: v for k, v in SIMULATORS["devices"].items() if k in {"main_camera", "mount"}}
    profile = {**SIMULATORS, "devices": devices}
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        use_site(client, SITE)
        response = client.put("/api/storage/destination", json={"destination": "internal"})
        assert response.status_code == 204, response.text
        assert client.put("/api/profiles/stack", json=profile).status_code == 204
        assert client.post("/api/equipment/connect", json={"profile": "stack"}).status_code == 202
        wait(client, lambda s: s.get("mount") is not None and "main_camera" in s.get("cameras", {}))
        utc = datetime.now(UTC).isoformat()
        assert client.post("/api/clock", json={"utc": utc, "utc_offset": -3}).status_code == 200
        if state(client)["mount"]["parked"]:
            assert client.post("/api/mount/unpark").status_code == 204
        response = client.post(
            "/api/cameras/main_camera/settings",
            json={"region": "full", "binning": 1, "frame_type": "light"},
        )
        assert response.status_code in (200, 202, 204), response.text
        try:
            yield client
        finally:
            client.put("/api/stack", json={"on": False})
            client.post("/api/mount/abort")


def goto(client: TestClient, ra: float, dec: float) -> None:
    response = client.post(
        "/api/mount/goto", json={"frame": "j2000", "ra": ra, "dec": dec, "force": True}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(client, finished(job_id))
    assert state(client)["jobs"][job_id]["state"] == "succeeded", state(client)["jobs"][job_id]
    wait(client, lambda s: not s["mount"]["slewing"] and abs(s["mount"]["dec_j2000"] - dec) < 0.5)


def expose(client: TestClient, *, save: bool = True) -> None:
    response = client.post("/api/cameras/main_camera/expose", json={"exposure": 1, "save": save})
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(client, finished(job_id))
    assert state(client)["jobs"][job_id]["state"] == "succeeded", state(client)["jobs"][job_id]


def stacked(frames: int) -> Callable[[dict[str, Any]], bool]:
    def done(s: dict[str, Any]) -> bool:
        current = s["stack"]["current"]
        last = current and current["last"]
        return bool(last) and current["frames"] + current["rejected"] >= frames

    return done


def test_frames_stack_as_they_arrive(api: TestClient) -> None:
    """Two frames, the second unsaved (Live view): quick enough for every pull request."""
    assert api.put("/api/stack", json={"on": True}).status_code == 204
    assert api.post("/api/stack/reset").status_code == 204
    expose(api)
    wait(api, stacked(1))
    expose(api, save=False)
    wait(api, stacked(2))
    current = state(api)
    AppState.model_validate(current)
    stack = current["stack"]["current"]
    assert stack["frames"] == 2, stack
    assert stack["camera"] == "CCD Simulator"
    assert stack["last"]["accepted"], stack["last"]
    assert stack["last"]["stars"] >= 6
    assert stack["preview"]["url"].startswith("/api/previews/")
    assert api.get(stack["preview"]["url"]).status_code == 200


@pytest.mark.slow
def test_a_dither_is_followed(api: TestClient) -> None:
    ra = state(api)["mount"]["ra_j2000"]
    goto(api, ra, DEC)
    assert api.put("/api/stack", json={"on": True}).status_code == 204
    assert api.post("/api/stack/reset").status_code == 204
    expose(api)
    wait(api, stacked(1))
    goto(api, ra, DEC + NUDGE)
    expose(api)
    wait(api, stacked(2))
    stack = state(api)["stack"]["current"]
    assert stack["frames"] == 2, stack
    last = stack["last"]
    assert last["accepted"], last
    # The nudge moved the stars by a few pixels, and the stack followed them.
    assert abs(last["shift"][0]) + abs(last["shift"][1]) > 2, last
    assert abs(last["rotation"]) < 0.5
