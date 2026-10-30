# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Connecting the simulator rig through the API, starting a driver through the FIFO."""

import json
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

# The simulator rig of dev/profiles/. The dev indiserver preloads its drivers except
# the weather simulator, which stands in for a power box (none is simulated) and is
# started through the FIFO.
SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)


@pytest.fixture
def api(indi_address: tuple[str, int], indi_fifo: Path) -> Iterator[TestClient]:
    host, port = indi_address
    settings = Settings(indi_host=host, indi_port=port, indi_fifo=indi_fifo)
    with TestClient(create_app(settings)) as client:
        yield client


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, current.get("equipment")
        time.sleep(0.2)


def test_connect_and_disconnect_simulator_profile(api: TestClient) -> None:
    assert api.put("/api/profiles/simulators", json=SIMULATORS).status_code == 204
    assert api.get("/api/profiles/simulators").json()["name"] == "Simulators"

    assert api.post("/api/equipment/connect", json={"profile": "simulators"}).status_code == 202
    wait(api, lambda s: s["equipment"]["connection"] == "connected")
    current = state(api)
    AppState.model_validate(current)
    devices = current["equipment"]["devices"]
    assert {role: d["status"] for role, d in devices.items()} == dict.fromkeys(
        SIMULATORS["devices"], "ready"
    ), devices
    assert devices["main_camera"]["device"] == "CCD Simulator"
    assert devices["guide_camera"]["device"] == "Guide Simulator"
    assert "Weather Simulator" in current["indi"]["devices"]

    assert api.post("/api/equipment/disconnect").status_code == 202
    # Well within DISCONNECT_TIMEOUT: drivers acknowledge (Idle) at once.
    wait(api, lambda s: s["equipment"]["connection"] == "disconnected", timeout=5)
    # Stopped because NOCS started it; the preloaded simulators keep running.
    wait(api, lambda s: "Weather Simulator" not in s["indi"]["devices"], timeout=10)
    indi = state(api)["indi"]["devices"]
    assert "CCD Simulator" in indi
    assert (
        indi["CCD Simulator"]["properties"]["CONNECTION"]["elements"]["CONNECT"]["value"] is False
    )


def test_profile_api_errors(api: TestClient) -> None:
    assert api.get("/api/profiles/nothing").status_code == 404
    assert api.put("/api/profiles/Bad Id", json=SIMULATORS).status_code == 422
    assert api.put("/api/profiles/x", json={"name": ""}).status_code == 422
    assert api.post("/api/equipment/connect", json={"profile": "nothing"}).status_code == 404
    assert api.delete("/api/profiles/nothing").status_code == 404


def test_driver_catalog(indi_address: tuple[str, int], indi_fifo: Path) -> None:
    host, port = indi_address
    # The dev container copies the catalog next to its FIFO.
    settings = Settings(
        indi_host=host, indi_port=port, indi_drivers_dir=indi_fifo.parent / "drivers"
    )
    with TestClient(create_app(settings)) as api:
        drivers = {d["driver"] for d in api.get("/api/indi/drivers").json()}
    assert {"indi_simulator_ccd", "indi_lx200am5", "indi_pegasus_ppba"} <= drivers
