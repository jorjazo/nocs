# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Autofocus through the API, against the simulators at 1000 mm (see simfocus)."""

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner
from simfocus import APERTURE, FOCAL_LENGTH, FOCUSER, ORION, SAMPLE_POSITIONS, vertex

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings

pytestmark = pytest.mark.indi

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
STEP = 4000
"""±16000 steps at 9 points: the ends at ~2.7 times the best HFR."""


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {
            k: current.get(k) for k in ("focuser", "autofocus", "jobs")
        }
        time.sleep(0.1)


def finished(job_id: str) -> Callable[[dict[str, Any]], bool]:
    return lambda s: s["jobs"][job_id]["state"] != "running"


def set_property(api: TestClient, device: str, name: str, values: dict[str, Any]) -> None:
    response = api.post(f"/api/indi/devices/{device}/properties/{name}", json={"values": values})
    assert response.status_code == 202, response.text


def move(api: TestClient, position: int) -> None:
    response = api.post("/api/focuser/move", json={"position": position})
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(api, finished(job_id))
    assert state(api)["jobs"][job_id]["state"] == "succeeded"


def fwhm(api: TestClient) -> float:
    properties = state(api)["indi"]["devices"][FOCUSER]["properties"]
    return properties["FWHM"]["elements"]["SIM_FWHM"]["value"]


def focus(api: TestClient, **request: Any) -> str:
    response = api.post("/api/autofocus", json={"step": STEP, "exposure": 1, **request})
    assert response.status_code == 202, response.text
    return response.json()["job"]


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
    devices = {
        k: v for k, v in SIMULATORS["devices"].items() if k in {"main_camera", "mount", "focuser"}
    }
    profile = {
        **SIMULATORS,
        "devices": devices,
        "imaging": {"focal_length": FOCAL_LENGTH, "aperture": APERTURE},
    }
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        assert client.put("/api/profiles/focus", json=profile).status_code == 204
        assert client.post("/api/equipment/connect", json={"profile": "focus"}).status_code == 202
        wait(
            client,
            lambda s: (
                s.get("focuser") is not None
                and s.get("mount") is not None
                and "main_camera" in s.get("cameras", {})
            ),
        )
        client.post("/api/cameras/main_camera/settings", json={"binning": 1, "region": "full"})
        if state(client)["mount"]["parked"]:
            assert client.post("/api/mount/unpark").status_code == 204
        set_property(client, "Telescope Simulator", "ON_COORD_SET", {"TRACK": True})
        ra, dec = ORION
        set_property(client, "Telescope Simulator", "EQUATORIAL_EOD_COORD", {"RA": ra, "DEC": dec})
        wait(client, lambda s: not s["mount"]["slewing"])
        start = state(client)["focuser"]["position"]
        try:
            yield client
        finally:
            client.post("/api/mount/abort")
            move(client, start)


@pytest.fixture(scope="module")
def best(api: TestClient) -> float:
    """The simulator's best focus, from its FWHM."""
    samples: list[tuple[float, float]] = []
    for position in SAMPLE_POSITIONS:
        move(api, position)
        samples.append((position, fwhm(api)))
    return vertex(samples)


def test_autofocus_finds_the_simulators_focus(api: TestClient, best: float) -> None:
    start = round(best) + 3000
    move(api, start)
    job_id = focus(api)
    wait(api, finished(job_id), timeout=180)
    current = state(api)
    AppState.model_validate(current)
    job, result = current["jobs"][job_id], current["autofocus"]
    assert job["state"] == "succeeded", (job, result)
    assert result["position"] == pytest.approx(best, abs=STEP / 4)
    assert current["focuser"]["position"] == result["position"]
    assert result["hfr"] < result["start_hfr"]
    assert result["fit"]["r_squared"] > 0.9
    assert len(result["points"]) >= 9


def test_cancelling_autofocus_puts_the_focuser_back(api: TestClient, best: float) -> None:
    start = round(best) - 2000
    move(api, start)
    job_id = focus(api)
    wait(api, lambda s: len((s.get("autofocus") or {}).get("points", [])) >= 2, timeout=60)
    assert api.post(f"/api/jobs/{job_id}/cancel").status_code in (200, 202, 204)
    wait(api, finished(job_id))
    current = state(api)
    assert current["jobs"][job_id]["state"] == "cancelled"
    assert current["autofocus"]["state"] == "cancelled"
    assert current["focuser"]["position"] == start


def test_autofocus_without_stars_fails_where_it_is(api: TestClient) -> None:
    start = state(api)["focuser"]["position"]
    set_property(api, "CCD Simulator", "SIMULATOR_SETTINGS", {"SIM_LIMITINGMAG": 0})
    try:
        job_id = focus(api)
        wait(api, finished(job_id))
    finally:
        set_property(api, "CCD Simulator", "SIMULATOR_SETTINGS", {"SIM_LIMITINGMAG": 17})
    current = state(api)
    assert current["jobs"][job_id]["state"] == "failed"
    assert current["autofocus"]["problem"] == "no_stars"
    assert current["focuser"]["position"] == start
