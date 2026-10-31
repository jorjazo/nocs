# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""PHD2 picks up the settings nocsd renders for the simulator rig, and loops with them."""

import asyncio
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import Phd2Setup
from fastapi.testclient import TestClient
from owner import pair_owner
from simfocus import ORION

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings
from nocs.guiding import Phd2Client, pixel_scale

pytestmark = [pytest.mark.indi, pytest.mark.phd2]

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)


@pytest.fixture
def api(indi_address: tuple[str, int], indi_fifo: Path, phd2: Phd2Setup) -> Iterator[TestClient]:
    host, port = indi_address
    settings = Settings(
        indi_host=host,
        indi_port=port,
        indi_fifo=indi_fifo,
        phd2_host=phd2.host,
        phd2_port=phd2.port,
        phd2_settings=phd2.settings,
        phd2_indi_host=phd2.indi_host,
        phd2_indi_port=7624,
    )
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        yield client
        # Stop the drivers NOCS started (the weather simulator), as the other tests expect.
        client.post("/api/equipment/disconnect")
        wait(client, lambda s: "Weather Simulator" not in s["indi"]["devices"], timeout=15)


def expect(response: Any, status: int) -> None:
    assert response.status_code == status, response.text


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, current.get("guiding")
        time.sleep(0.2)


def test_phd2_runs_the_profiles_settings_and_takes_the_guide_camera(
    api: TestClient, phd2: Phd2Setup
) -> None:
    wait(api, lambda s: s["guiding"]["phd2"]["connected"])
    expect(api.put("/api/profiles/simulators", json=SIMULATORS), 204)
    expect(api.post("/api/equipment/connect", json={"profile": "simulators"}), 202)
    wait(api, lambda s: s["guiding"]["settings"] == "applied", timeout=90)
    current = state(api)
    AppState.model_validate(current)
    guiding = current["guiding"]
    assert guiding["managed"]
    assert guiding["profile"].startswith("NOCS simulators ")
    assert guiding["phd2"]["version"]
    sensor = current["indi"]["devices"]["Guide Simulator"]["properties"]["CCD_INFO"]
    pixel = sensor["elements"]["CCD_PIXEL_SIZE_X"]["value"]
    focal = SIMULATORS["guiding"]["focal_length"]

    async def check() -> None:
        async with Phd2Client(phd2.host, phd2.port) as client:
            assert await client.call("get_pixel_scale") == pytest.approx(
                pixel_scale(pixel, focal), abs=0.01
            )
            equipment = await client.call("get_current_equipment")
            assert isinstance(equipment, dict)
            assert "Guide Simulator" in str(equipment["camera"])
            assert "Telescope Simulator" in str(equipment["mount"])

    asyncio.run(check())

    # PHD2 loops on the guide camera, which is PHD2's meanwhile (ADR 0023).
    expect(api.post("/api/guiding/loop", json={"exposure": 1}), 204)
    looping = ("Looping", "Selected")  # "Selected": looping with a star selected
    wait(api, lambda s: s["guiding"]["equipment"] and s["guiding"]["app_state"] in looping)
    assert state(api)["cameras"]["guide_camera"]["used_by"] == "phd2"
    refused = api.post("/api/cameras/guide_camera/expose", json={"exposure": 1})
    assert refused.status_code == 409, refused.text
    assert "guiding" in refused.json()["detail"]
    # Live view shows PHD2's frames.
    first = state(api)["cameras"]["guide_camera"]["preview"]
    wait(api, lambda s: _new_preview(s, first) is not None, timeout=30)
    newer = _new_preview(state(api), first)
    assert newer is not None
    assert newer["exposure"] == 1
    assert api.get(newer["url"]).status_code == 200
    AppState.model_validate(state(api))

    expect(api.post("/api/guiding/stop"), 204)
    assert state(api)["guiding"]["app_state"] == "Stopped"
    expect(api.post("/api/guiding/disconnect"), 204)
    current = state(api)
    assert not current["guiding"]["equipment"]
    assert current["cameras"]["guide_camera"]["used_by"] is None
    # NOCS has the camera back.
    response = api.post("/api/cameras/guide_camera/expose", json={"exposure": 0.5})
    assert response.status_code == 202, response.text


def _new_preview(current: dict[str, Any], before: dict[str, Any] | None) -> dict[str, Any] | None:
    preview = current["cameras"]["guide_camera"]["preview"]
    if preview is None or (before is not None and preview["url"] == before["url"]):
        return None
    return preview


def point_at_stars(api: TestClient) -> None:
    """Unpark the simulated mount and track a field rich in guide stars."""
    if state(api)["mount"]["parked"]:
        expect(api.post("/api/mount/unpark"), 204)
        wait(api, lambda s: not s["mount"]["parked"] and not s["mount"]["parking"])
    set_property(api, "Telescope Simulator", "ON_COORD_SET", {"TRACK": True})
    ra, dec = ORION

    def there(current: dict[str, Any]) -> bool:
        mount = current["mount"]
        arrived = abs(mount["ra"] - ra) < 0.02 and abs(mount["dec"] - dec) < 0.2
        return arrived and not mount["slewing"]

    set_property(api, "Telescope Simulator", "EQUATORIAL_EOD_COORD", {"RA": ra, "DEC": dec})
    wait(api, there, timeout=120)


def set_property(api: TestClient, device: str, name: str, values: dict[str, Any]) -> None:
    response = api.post(f"/api/indi/devices/{device}/properties/{name}", json={"values": values})
    assert response.status_code == 202, response.text


def start_guiding(api: TestClient, **request: Any) -> dict[str, Any]:
    response = api.post("/api/guiding/guide", json=request)
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(api, lambda s: s["jobs"][job_id]["state"] != "running", timeout=300)
    job = state(api)["jobs"][job_id]
    assert job["state"] == "succeeded", (job["error"], job["message"])
    return job["result"]


def test_calibrate_guide_and_stop_for_the_mount(api: TestClient) -> None:
    expect(api.put("/api/profiles/simulators", json=SIMULATORS), 204)
    expect(api.post("/api/equipment/connect", json={"profile": "simulators"}), 202)
    wait(api, lambda s: s["guiding"]["settings"] == "applied", timeout=90)
    wait(api, lambda s: s["mount"] is not None)
    point_at_stars(api)
    expect(api.post("/api/guiding/connect"), 204)
    expect(api.put("/api/guiding/exposure", json={"exposure": 1}), 204)

    settle = {"pixels": 1.5, "time": 5, "timeout": 90}
    result = start_guiding(api, recalibrate=True, settle=settle)
    assert result["calibrated"] is True
    current = state(api)
    AppState.model_validate(current)
    guiding = current["guiding"]
    assert guiding["app_state"] == "Guiding"
    assert guiding["calibration"] is not None
    assert guiding["calibration"]["ra_rate"] > 0

    # The mount is PHD2's while it guides (ADR 0023).
    refused = api.post("/api/mount/park")
    assert refused.status_code == 409, refused.text
    assert "guiding" in refused.json()["detail"]
    response = api.post("/api/mount/park", json={"stop_guiding": True})
    assert response.status_code == 202, response.text
    assert state(api)["guiding"]["app_state"] == "Stopped"
    # Only the guiding mattered: stop the park so that the stars are near.
    expect(api.post("/api/mount/abort"), 202)
    park = response.json()["job"]
    wait(api, lambda s: s["jobs"][park]["state"] != "running", timeout=30)

    # Back on the stars, the calibration is reused.
    point_at_stars(api)
    result = start_guiding(api, settle=settle)
    assert result["calibrated"] is False
    expect(api.post("/api/guiding/stop"), 204)
    expect(api.post("/api/guiding/disconnect"), 204)
