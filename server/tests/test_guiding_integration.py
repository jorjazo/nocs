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

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings
from nocs.guiding import Phd2Client, Phd2Event, pixel_scale

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


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, current.get("guiding")
        time.sleep(0.2)


def test_phd2_runs_and_loops_with_the_profiles_settings(api: TestClient, phd2: Phd2Setup) -> None:
    wait(api, lambda s: s["guiding"]["phd2"]["connected"])
    assert api.put("/api/profiles/simulators", json=SIMULATORS).status_code == 204
    assert api.post("/api/equipment/connect", json={"profile": "simulators"}).status_code == 202
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
            looping, stopped = asyncio.Event(), asyncio.Event()

            def on_message(message: object) -> None:
                if isinstance(message, Phd2Event):
                    if message.name == "LoopingExposures":
                        looping.set()
                    elif message.name == "LoopingExposuresStopped":
                        stopped.set()

            client.add_listener(on_message)
            assert await client.call("get_pixel_scale") == pytest.approx(
                pixel_scale(pixel, focal), abs=0.01
            )
            equipment = await client.call("get_current_equipment")
            assert isinstance(equipment, dict)
            assert "Guide Simulator" in str(equipment["camera"])
            assert "Telescope Simulator" in str(equipment["mount"])
            await client.call("set_connected", [True], timeout=60)
            try:
                await client.call("set_exposure", [1000])
                await client.call("loop")
                await asyncio.wait_for(looping.wait(), 30)
            finally:
                # stop_capture answers at once; the exposure in progress ends later, and
                # PHD2 refuses to disconnect until then.
                await client.call("stop_capture")
                await asyncio.wait_for(stopped.wait(), 30)
                await client.call("set_connected", [False], timeout=60)

    asyncio.run(check())
    wait(api, lambda s: s["guiding"]["app_state"] in ("Stopped", "Selected"), timeout=20)
