# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A driver frozen with SIGSTOP mid-exposure and mid-go-to is noticed, restarted and
ready again (ADR 0030), against the simulators.

Freezing needs the indiserver container's name (NOCS_TEST_INDI_CONTAINER, ``dev-indi-1``
with compose) and ``docker``: drivers run as the container's own user.
"""

import json
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings
from nocs.devices import base as devices_base

pytestmark = pytest.mark.indi

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
SITE = {"name": "Diaguitas", "latitude": -30.03, "longitude": -70.65, "elevation": 1100}
SILENCE = 3.0
PROBE_TIMEOUT = 3.0


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {k: current.get(k) for k in ("equipment", "jobs")}
        time.sleep(0.1)


def role(api: TestClient, name: str) -> dict[str, Any]:
    return state(api)["equipment"]["devices"][name]


@pytest.fixture(scope="module")
def container() -> str:
    value = os.environ.get("NOCS_TEST_INDI_CONTAINER")
    if not value:
        pytest.skip("NOCS_TEST_INDI_CONTAINER not set (e.g. dev-indi-1)")
    return value


@pytest.fixture(scope="module")
def freeze(container: str) -> Iterator[Callable[[str], None]]:
    """Stop a driver's process; every driver frozen is let go at the end, whatever happened."""
    frozen: set[str] = set()

    def signal(driver: str, sig: str) -> None:
        # By command line: a process's name stops at 15 characters.
        subprocess.run(
            ["docker", "exec", container, "pkill", f"-{sig}", "-f", f"^{driver}$"],
            check=True,
            capture_output=True,
        )

    def stop(driver: str) -> None:
        signal(driver, "STOP")
        frozen.add(driver)

    yield stop
    for driver in frozen:
        # A driver restarted meanwhile is a new process: nothing to continue.
        subprocess.run(
            ["docker", "exec", container, "pkill", "-CONT", "-f", f"^{driver}$"],
            capture_output=True,
        )


@pytest.fixture(scope="module")
def api(
    tmp_path_factory: pytest.TempPathFactory, container: str, freeze: Callable[[str], None]
) -> Iterator[TestClient]:
    value, fifo = os.environ.get("NOCS_TEST_INDI"), os.environ.get("NOCS_TEST_INDI_FIFO")
    if not value or not fifo:
        pytest.skip("NOCS_TEST_INDI and NOCS_TEST_INDI_FIFO not set")
    host, _, port = value.rpartition(":")
    settings = Settings(
        indi_host=host,
        indi_port=int(port),
        indi_fifo=Path(fifo),
        config_dir=tmp_path_factory.mktemp("config"),
        data_dir=tmp_path_factory.mktemp("data"),
    )
    profile = {**SIMULATORS, "devices": dict(SIMULATORS["devices"]), "site": SITE}
    profile["devices"].pop("weather")  # not relevant here
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(devices_base, "SILENCE", SILENCE)
        patch.setattr(devices_base, "PROBE_TIMEOUT", PROBE_TIMEOUT)
        with TestClient(create_app(settings)) as client:
            pair_owner(client)
            response = client.put("/api/storage/destination", json={"destination": "internal"})
            assert response.status_code == 204, response.text
            assert client.put("/api/profiles/sim", json=profile).status_code == 204
            response = client.post("/api/equipment/connect", json={"profile": "sim"})
            assert response.status_code == 202
            wait(client, lambda s: s["equipment"]["connection"] == "connected", timeout=60)
            yield client


def restarted(api: TestClient, name: str) -> float:
    """Restart a role's driver from the API; seconds until it is ready again."""
    start = time.monotonic()
    response = api.post(f"/api/equipment/roles/{name}/restart")
    assert response.status_code == 204, response.text
    wait(api, lambda s: s["equipment"]["devices"][name]["status"] == "ready")
    return time.monotonic() - start


def test_a_camera_frozen_mid_exposure(api: TestClient, freeze: Callable[[str], None]) -> None:
    job = api.post("/api/cameras/main_camera/expose", json={"exposure": 60}).json()["job"]
    wait(api, lambda s: s["cameras"]["main_camera"]["exposing"])
    frozen = time.monotonic()
    freeze("indi_simulator_ccd")

    wait(api, lambda s: s["equipment"]["devices"]["main_camera"]["status"] == "unresponsive")
    noticed = time.monotonic() - frozen
    # Long before the exposure would have ended: silence, then an unanswered probe.
    assert SILENCE + PROBE_TIMEOUT - 1 < noticed < SILENCE + PROBE_TIMEOUT + 5
    current = state(api)
    AppState.model_validate(current)
    main = current["equipment"]["devices"]["main_camera"]
    assert main["error"].startswith("CCD Simulator is not answering")
    assert main["unresponsive_since"] is not None
    wait(api, lambda s: s["jobs"][job]["state"] != "running", timeout=5)
    assert "not answering" in (state(api)["jobs"][job]["error"] or "")
    # The guide camera is another driver: unaffected.
    assert role(api, "guide_camera")["status"] == "ready"

    assert restarted(api, "main_camera") < 15
    assert role(api, "main_camera")["unresponsive_since"] is None
    job = api.post("/api/cameras/main_camera/expose", json={"exposure": 0.5}).json()["job"]
    wait(api, lambda s: s["jobs"][job]["state"] != "running")
    assert state(api)["jobs"][job]["state"] == "succeeded"


def test_a_mount_frozen_mid_go_to(api: TestClient, freeze: Callable[[str], None]) -> None:
    response = api.post("/api/clock", json={"utc": datetime.now(UTC).isoformat(), "utc_offset": -3})
    assert response.status_code == 200
    wait(api, lambda s: s["mount"] is not None and s["mount"]["time_sent"], timeout=10)
    if state(api)["mount"]["parked"]:
        assert api.post("/api/mount/unpark").status_code == 204
    az = state(api)["mount"]["az"]
    target = {"frame": "altaz", "alt": 40, "az": (az + 180) % 360}
    response = api.post("/api/mount/goto", json=target)
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    wait(api, lambda s: s["mount"]["slewing"], timeout=5)
    time.sleep(1)
    frozen = time.monotonic()
    freeze("indi_simulator_telescope")

    wait(api, lambda s: s["equipment"]["devices"]["mount"]["status"] == "unresponsive")
    assert time.monotonic() - frozen < SILENCE + PROBE_TIMEOUT + 5
    wait(api, lambda s: s["jobs"][job]["state"] != "running", timeout=5)
    assert state(api)["jobs"][job]["state"] == "failed"
    assert "not answering" in (state(api)["jobs"][job]["error"] or "")

    assert restarted(api, "mount") < 15
    wait(api, lambda s: s["mount"] is not None)
    api.post("/api/mount/abort")
    api.post("/api/mount/unpark")
