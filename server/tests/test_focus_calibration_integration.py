# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Focuser calibration through the API, against the simulators at 1000 mm (ADR 0044).

The focuser simulator has no backlash: this checks the plain path, the driver's own
compensation refused and turned off, and what is kept.
"""

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
from nocs.services.indi_bridge import COALESCE

pytestmark = [pytest.mark.indi, pytest.mark.slow]

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
STEP = 4000


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {
            k: current.get(k) for k in ("focuser", "focus_calibration", "jobs")
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
    time.sleep(COALESCE)  # the mirror's last update of a burst can be that late (ADR 0037)
    properties = state(api)["indi"]["devices"][FOCUSER]["properties"]
    return properties["FWHM"]["elements"]["SIM_FWHM"]["value"]


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
        "imaging": {
            "focal_length": FOCAL_LENGTH,
            "aperture": APERTURE,
            "autofocus": {"step": STEP, "exposure": 1},
        },
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
        wait(client, lambda s: not s["mount"]["slewing"] and abs(s["mount"]["dec"] - dec) < 0.5)
        start = state(client)["focuser"]["position"]
        try:
            yield client
        finally:
            client.post("/api/mount/abort")
            set_property(client, FOCUSER, "FOCUS_BACKLASH_TOGGLE", {"INDI_DISABLED": True})
            move(client, start)


def test_driver_compensation_is_refused_and_turned_off(api: TestClient) -> None:
    set_property(api, FOCUSER, "FOCUS_BACKLASH_TOGGLE", {"INDI_ENABLED": True})
    wait(api, lambda s: s["focuser"]["driver_backlash"] is not None, timeout=10)
    response = api.post("/api/focuser/calibrate", json={})
    assert response.status_code == 422, response.text
    assert "compensates" in response.json()["detail"]
    assert api.delete("/api/focuser/driver-backlash").status_code == 204
    wait(api, lambda s: s["focuser"]["driver_backlash"] is None, timeout=10)


def test_calibration_on_the_simulators(api: TestClient) -> None:
    samples: list[tuple[float, float]] = []
    for position in SAMPLE_POSITIONS:
        move(api, position)
        samples.append((position, fwhm(api)))
    best = vertex(samples)
    move(api, round(best) + STEP)
    response = api.post("/api/focuser/calibrate", json={})
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(api, finished(job_id), timeout=480)
    current = state(api)
    AppState.model_validate(current)
    job, result = current["jobs"][job_id], current["focus_calibration"]
    assert job["state"] == "succeeded", {
        k: result[k] for k in ("problem", "detail", "best", "ruler", "reversals", "trips", "noise")
    }
    assert result["best"]["position"] == pytest.approx(best, abs=STEP / 2)
    width = result["best"]["width"]
    assert [r["towards"] for r in result["reversals"]] == ["inward", "outward"] * 2
    # No backlash in the simulator: what is "lost" is the ruler's error.
    assert all(abs(r["lost"]) < width for r in result["reversals"]), result["reversals"]
    assert all(t["ok"] for t in result["trips"])
    assert result["microns_per_step"] is not None
    assert result["focus_zone"] is not None
    focuser = current["focuser"]
    assert focuser["position"] == result["best"]["position"]
    assert focuser["calibration"]["profile"] == "focus"
    assert focuser["calibration"]["overshoot"] == result["overshoot"]
    assert focuser["backlash"]["overshoot"] == result["overshoot"]
