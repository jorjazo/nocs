# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Calibration frames against the simulators (ADR 0036): the darks and bias sequence."""

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.config import Settings

pytestmark = pytest.mark.indi

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {
            k: current.get(k) for k in ("sequence", "jobs", "cameras", "flats")
        }
        time.sleep(0.2)


def finished(job_id: str) -> Callable[[dict[str, Any]], bool]:
    return lambda s: s["jobs"][job_id]["state"] != "running"


def sequence_finished(s: dict[str, Any]) -> bool:
    run: dict[str, Any] | None = (s.get("sequence") or {}).get("run")
    return run is not None and run["state"] == "finished"


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
    roles = {"main_camera", "focuser", "filter_wheel"}
    profile = {
        **SIMULATORS,
        "devices": {k: v for k, v in SIMULATORS["devices"].items() if k in roles},
    }
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        assert client.put("/api/profiles/calibration", json=profile).status_code == 204
        response = client.post("/api/equipment/connect", json={"profile": "calibration"})
        assert response.status_code == 202, response.text
        wait(
            client,
            lambda s: (
                s.get("focuser") is not None
                and s.get("filter_wheel") is not None
                and "main_camera" in s.get("cameras", {})
            ),
        )
        settings_response = client.post(
            "/api/cameras/main_camera/settings", json={"binning": 2, "region": "full"}
        )
        assert settings_response.status_code == 204, settings_response.text
        try:
            yield client
        finally:
            client.post("/api/sequence/stop", json={"run_end": False, "now": True})
            client.post("/api/cameras/main_camera/cooling", json={"on": False})
            client.post("/api/cameras/main_camera/settings", json={"binning": 1})


def test_darks_and_bias_for_a_night(api: TestClient) -> None:
    response = api.post(
        "/api/cameras/main_camera/expose", json={"exposure": 0.5, "frame_type": "light", "count": 2}
    )
    assert response.status_code == 202, response.text
    wait(api, finished(response.json()["job"]))
    assert state(api)["jobs"][response.json()["job"]]["state"] == "succeeded"
    night = api.get("/api/nights").json()[0]

    report = api.get(
        "/api/calibration", params={"night": night["id"], "darks": 2, "bias": 3}
    ).json()
    assert [(n["kind"], n["count"]) for n in report["needs"]] == [
        ("bias", 3),
        ("dark", 2),
        ("flat", 20),
    ]
    response = api.post(
        "/api/calibration/sequence",
        json={"night": night["id"], "darks": 2, "bias": 3, "warm": False},
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert (created["id"], created["frames"], created["left_out"]) == ("calibration", 5, [])

    response = api.post("/api/sequences/calibration/start")
    assert response.status_code == 202, response.text
    wait(api, sequence_finished, timeout=300)
    run = state(api)["sequence"]["run"]
    assert run["outcome"] == "completed", run

    report = api.get(
        "/api/calibration", params={"night": night["id"], "darks": 2, "bias": 3}
    ).json()
    [group] = report["groups"]
    assert group["darks"]["frames"] == 2
    assert group["bias"]["frames"] == 3
    assert [n["kind"] for n in report["needs"]] == ["flat"]
    types = {g["frame_type"] for g in api.get("/api/nights").json()[0]["groups"]}
    assert types == {"light", "dark", "bias"}


def test_panel_flats(api: TestClient) -> None:
    """The CCD simulator's flats are uniform and grow with the exposure, like a panel."""
    wheel = state(api)["filter_wheel"]
    names = [name for name in wheel["names"] if name][:2]
    plan = {
        "filters": [{"filter": name, "count": 2} for name in names],
        "level": 0.4,
        "max_exposure": 20,
    }
    response = api.post("/api/flats", json=plan)
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(api, finished(job_id), timeout=300)
    current = state(api)
    assert current["jobs"][job_id]["state"] == "succeeded", (
        current["jobs"][job_id],
        current["flats"],
    )
    flats = current["flats"]
    assert [(f["filter"], f["done"], f["state"]) for f in flats["filters"]] == [
        (name, 2, "done") for name in names
    ]
    frames = api.get("/api/frames", params={"type": "flat"}).json()
    assert len(frames) == 4
    assert {f["filter"] for f in frames} == set(names)
    assert all(f["path"].split("/")[1] == "Flat" for f in frames)
