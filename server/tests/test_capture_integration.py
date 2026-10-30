# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Camera settings, cooling and exposures through the API, against the simulators."""

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings

pytestmark = pytest.mark.indi

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
SMALL = {"x": 0, "y": 0, "width": 320, "height": 240}


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {k: current.get(k) for k in ("cameras", "jobs")}
        time.sleep(0.1)


def camera(api: TestClient, role: str = "main_camera") -> dict[str, Any]:
    return state(api)["cameras"][role]


def job(api: TestClient, job_id: str) -> dict[str, Any]:
    return state(api)["jobs"][job_id]


def finished(job_id: str) -> Callable[[dict[str, Any]], bool]:
    return lambda s: s["jobs"][job_id]["state"] != "running"


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("data")


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory, data_dir: Path) -> Iterator[TestClient]:
    value = os.environ.get("NOCS_TEST_INDI")
    if not value:
        pytest.skip("NOCS_TEST_INDI not set")
    host, _, port = value.rpartition(":")
    settings = Settings(
        indi_host=host,
        indi_port=int(port),
        config_dir=tmp_path_factory.mktemp("config"),
        data_dir=data_dir,
    )
    profile = {**SIMULATORS, "devices": dict(SIMULATORS["devices"])}
    profile["devices"].pop("power_box")  # needs the FIFO; not relevant here
    with TestClient(create_app(settings)) as client:
        assert client.put("/api/profiles/sim", json=profile).status_code == 204
        assert client.post("/api/equipment/connect", json={"profile": "sim"}).status_code == 202
        wait(client, lambda s: s["equipment"]["connection"] == "connected", timeout=60)
        wait(client, lambda s: {"main_camera", "guide_camera"} <= set(s.get("cameras", {})))
        try:
            yield client
        finally:
            # Leave the shared simulator as other tests expect it.
            client.post(
                "/api/cameras/main_camera/settings",
                json={"binning": 1, "region": "full", "frame_type": "light"},
            )
            client.post("/api/cameras/main_camera/cooling", json={"on": False})


def test_camera_state(api: TestClient) -> None:
    current = state(api)
    AppState.model_validate(current)
    main = current["cameras"]["main_camera"]
    assert main["device"] == "CCD Simulator"
    assert main["sensor"]["width"] > 0
    assert main["gain"] is not None
    assert main["gain_range"]["max"] > main["gain_range"]["min"]
    assert main["exposing"] is False
    assert current["cameras"]["guide_camera"]["device"] == "Guide Simulator"

    # Connecting pointed the camera at the rig's devices and optics (FITS headers).
    properties = current["indi"]["devices"]["CCD Simulator"]["properties"]
    snooped = {k: e["value"] for k, e in properties["ACTIVE_DEVICES"]["elements"].items()}
    assert snooped["ACTIVE_TELESCOPE"] == "Telescope Simulator"
    assert snooped["ACTIVE_FOCUSER"] == "Focuser Simulator"
    assert snooped["ACTIVE_FILTER"] == "Filter Simulator"
    assert properties["SCOPE_INFO"]["elements"]["FOCAL_LENGTH"]["value"] == 250


def test_settings(api: TestClient) -> None:
    response = api.post(
        "/api/cameras/main_camera/settings",
        json={"gain": 120, "offset": 10, "binning": 2, "region": SMALL, "frame_type": "dark"},
    )
    assert response.status_code == 204, response.text
    wait(api, lambda s: s["cameras"]["main_camera"]["region"] == SMALL)
    main = camera(api)
    assert (main["gain"], main["offset"], main["binning"], main["frame_type"]) == (
        120,
        10,
        [2, 2],
        "dark",
    )


def test_invalid_settings(api: TestClient) -> None:
    too_big = {"x": 0, "y": 0, "width": 100000, "height": 10}
    assert (
        api.post("/api/cameras/main_camera/settings", json={"region": too_big}).status_code == 422
    )
    assert api.post("/api/cameras/main_camera/settings", json={"gain": 1e9}).status_code == 422
    assert api.post("/api/cameras/main_camera/settings", json={"binning": 99}).status_code == 422
    assert api.post("/api/cameras/telescope/settings", json={}).status_code == 422


def test_expose_and_save(api: TestClient, data_dir: Path) -> None:
    api.post("/api/cameras/main_camera/settings", json={"region": SMALL, "binning": 1})
    response = api.post(
        "/api/cameras/main_camera/expose", json={"exposure": 1, "frame_type": "light"}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(api, finished(job_id))
    result = job(api, job_id)
    assert result["state"] == "succeeded", result
    frame = result["result"]
    path = Path(frame["path"])
    assert path.is_relative_to(data_dir / "frames")
    assert path.read_bytes().startswith(b"SIMPLE")
    assert (frame["exposure"], frame["frame_type"], frame["size"]) == (
        1,
        "light",
        path.stat().st_size,
    )
    assert camera(api)["last_frame"] == frame


def test_busy_camera_refuses_commands_and_cancel_aborts(api: TestClient) -> None:
    job_id = api.post("/api/cameras/main_camera/expose", json={"exposure": 30}).json()["job"]
    wait(api, lambda s: s["cameras"]["main_camera"]["exposing"])
    busy = api.post("/api/cameras/main_camera/settings", json={"gain": 100})
    assert busy.status_code == 409
    assert job_id in busy.json()["detail"]
    assert api.post("/api/cameras/main_camera/expose", json={"exposure": 1}).status_code == 409
    # The guide camera is a different resource.
    guide = api.post("/api/cameras/guide_camera/expose", json={"exposure": 0.1, "save": False})
    assert guide.status_code == 202

    assert api.post(f"/api/jobs/{job_id}/cancel").status_code == 202
    wait(api, finished(job_id))
    assert job(api, job_id)["state"] == "cancelled"
    wait(api, lambda s: not s["cameras"]["main_camera"]["exposing"], timeout=10)
    assert api.post(f"/api/jobs/{job_id}/cancel").status_code == 409
    assert api.post("/api/jobs/nope/cancel").status_code == 404

    guide_job = guide.json()["job"]
    wait(api, finished(guide_job))
    assert job(api, guide_job)["state"] == "succeeded"
    assert job(api, guide_job)["result"]["path"] is None


def test_cooling(api: TestClient) -> None:
    response = api.post(
        "/api/cameras/main_camera/cooling", json={"on": True, "target": -10, "ramp": 2}
    )
    assert response.status_code == 204, response.text
    wait(api, lambda s: s["cameras"]["main_camera"]["ramp"] == 2)
    assert camera(api)["target"] == -10
    assert api.post("/api/cameras/main_camera/cooling", json={"on": True}).status_code == 422
    assert api.post("/api/cameras/main_camera/cooling", json={"on": False}).status_code == 204
    assert camera(api)["target"] is None
