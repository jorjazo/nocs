# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Focuser and filter wheel through the API, against the INDI simulators."""

import os
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings

pytestmark = pytest.mark.indi

PROFILE = {
    "name": "Focuser and wheel",
    "devices": {
        "focuser": {"driver": "indi_simulator_focus"},
        "filter_wheel": {"driver": "indi_simulator_wheel"},
    },
}


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        keys = ("focuser", "filter_wheel", "jobs", "equipment")
        assert time.monotonic() < deadline, {k: current.get(k) for k in keys}
        time.sleep(0.05)


def finished(job_id: str) -> Callable[[dict[str, Any]], bool]:
    return lambda s: s["jobs"][job_id]["state"] != "running"


def job(api: TestClient, url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = api.post(url, json=body)
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(api, finished(job_id))
    return state(api)["jobs"][job_id]


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
        assert client.put("/api/profiles/accessories", json=PROFILE).status_code == 204
        connect = client.post("/api/equipment/connect", json={"profile": "accessories"})
        assert connect.status_code == 202
        wait(
            client,
            lambda s: (
                s.get("focuser") is not None
                and s.get("filter_wheel") is not None
                and s["filter_wheel"]["key"] is not None
            ),
        )
        names = state(client)["filter_wheel"]["names"]
        try:
            yield client
        finally:
            # The simulators are shared: leave the wheel's names as they were.
            client.put("/api/filter-wheel/names", json={"filters": names})


def test_state(api: TestClient) -> None:
    current = state(api)
    AppState.model_validate(current)
    assert current["focuser"]["device"] == "Focuser Simulator"
    wheel = current["filter_wheel"]
    assert wheel["device"] == "Filter Simulator"
    assert wheel["key"] == "device:Filter Simulator"  # the simulator has no serial number
    assert wheel["slots"] == len(wheel["names"]) > 1


def test_focuser_moves(api: TestClient) -> None:
    start = state(api)["focuser"]["position"]
    target = start + 1000 if start < 50000 else start - 1000
    done = job(api, "/api/focuser/move", {"position": target})
    assert done["state"] == "succeeded", done
    assert done["kind"] == "focus"
    assert state(api)["focuser"]["position"] == target
    done = job(api, "/api/focuser/move", {"steps": -300})
    assert done["state"] == "succeeded", done
    focuser = state(api)["focuser"]
    assert focuser["position"] == target - 300
    assert focuser["moving"] is False
    assert focuser["target"] is None


def test_focuser_refuses_bad_moves(api: TestClient) -> None:
    limit = state(api)["focuser"]["max_position"]
    assert api.post("/api/focuser/move", json={"position": limit + 1}).status_code == 422
    assert api.post("/api/focuser/move", json={"steps": 10, "position": 5}).status_code == 422
    assert api.post("/api/focuser/move", json={}).status_code == 422


def test_filter_names_and_selection(api: TestClient) -> None:
    slots = state(api)["filter_wheel"]["slots"]
    names = ["L", "R", "G", "B", "Ha", "OIII", "SII", "Dark"][:slots]
    names += [""] * (slots - len(names))
    response = api.put("/api/filter-wheel/names", json={"filters": names, "label": "Sim"})
    assert response.status_code == 204, response.text
    wait(api, lambda s: s["filter_wheel"]["names"] == names)
    wheel = state(api)["filter_wheel"]
    assert wheel["confirmed"] is True
    assert wheel["label"] == "Sim"

    done = job(api, "/api/filter-wheel/select", {"filter": "g"})
    assert done["state"] == "succeeded", done
    wheel = state(api)["filter_wheel"]
    assert (wheel["slot"], wheel["filter"]) == (3, "G")
    done = job(api, "/api/filter-wheel/select", {"slot": 1})
    assert state(api)["filter_wheel"]["filter"] == "L"

    assert api.post("/api/filter-wheel/select", json={"filter": "Lum"}).status_code == 422
    assert api.post("/api/filter-wheel/select", json={"slot": slots + 1}).status_code == 422
    bad = api.put("/api/filter-wheel/names", json={"filters": ["L"] * slots})
    assert bad.status_code == 422
