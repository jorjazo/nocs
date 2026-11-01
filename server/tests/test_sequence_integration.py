# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A sequence through the API, against the simulators (ADR 0031).

The site's longitude is chosen so that the Orion field of ``simfocus`` rises an
hour east of the meridian now: the mount refuses targets below the horizon, and
autofocus needs its stars.
"""

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
from simfocus import APERTURE, FOCAL_LENGTH, ORION

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings
from nocs.devices import Location
from nocs.mount.coords import horizontal_to_jnow, jnow_to_j2000

pytestmark = pytest.mark.indi

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
LATITUDE = -30.0


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {
            k: current.get(k) for k in ("sequence", "jobs", "mount", "cameras")
        }
        time.sleep(0.2)


def finished(job_id: str) -> Callable[[dict[str, Any]], bool]:
    return lambda s: s["jobs"][job_id]["state"] != "running"


def longitude_for_orion(now: datetime) -> float:
    """A longitude where Orion's field stands an hour east of the meridian now."""
    meridian = horizontal_to_jnow(60, 0, Location(LATITUDE, 0.0, 0.0), now)  # at longitude 0
    return ((ORION[0] - 1 - meridian.ra) * 15 + 180) % 360 - 180


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
    roles = {"main_camera", "mount", "focuser", "filter_wheel"}
    now = datetime.now(UTC)
    profile = {
        **SIMULATORS,
        "devices": {k: v for k, v in SIMULATORS["devices"].items() if k in roles},
        "imaging": {
            "focal_length": FOCAL_LENGTH,
            "aperture": APERTURE,
            "autofocus": {"step": 4000, "exposure": 1},
        },
        "site": {"name": "Sim", "latitude": LATITUDE, "longitude": longitude_for_orion(now)},
    }
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        assert client.put("/api/profiles/sequence", json=profile).status_code == 204
        response = client.post("/api/equipment/connect", json={"profile": "sequence"})
        assert response.status_code == 202, response.text
        wait(
            client,
            lambda s: (
                s.get("focuser") is not None
                and s.get("filter_wheel") is not None
                and s.get("mount") is not None
                and "main_camera" in s.get("cameras", {})
            ),
        )
        client.post("/api/cameras/main_camera/settings", json={"binning": 1, "region": "full"})
        response = client.post("/api/clock", json={"utc": now.isoformat(), "utc_offset": 0})
        assert response.status_code == 200, response.text
        wait(client, lambda s: s["mount"]["site_sent"] and s["mount"]["time_sent"])
        before = state(client)
        focus = before["focuser"]["position"]
        pointing = {"ra": before["mount"]["ra_j2000"], "dec": before["mount"]["dec_j2000"]}
        try:
            yield client
        finally:
            # Leave the simulators as found. Autofocus at 1000 mm makes stars too small
            # for the solver's tests at 250 mm, and the simulator parks on the meridian,
            # where the next test's field would cross it between two frames.
            client.post("/api/sequence/stop", json={"run_end": False, "now": True})
            client.post("/api/mount/abort")
            if state(client)["mount"]["parked"]:
                client.post("/api/mount/unpark")
            for path, body in (
                ("/api/focuser/move", {"position": focus}),
                ("/api/mount/goto", {"frame": "j2000", **pointing, "force": True}),
            ):
                response = client.post(path, json=body)
                if response.status_code == 202:
                    wait(client, finished(response.json()["job"]))


def test_a_two_filter_sequence_focuses_takes_its_frames_and_parks(api: TestClient) -> None:
    if state(api)["mount"]["parked"]:
        assert api.post("/api/mount/unpark").status_code == 204
    names = [n for n in state(api)["filter_wheel"]["names"] if n][:2]
    assert len(names) == 2, state(api)["filter_wheel"]
    target = jnow_to_j2000(*ORION, datetime.now(UTC))
    sequence = {
        "name": "Two filters",
        "start": {"children": [{"kind": "cool", "temperature": 5, "ramp": 0}, {"kind": "unpark"}]},
        "targets": {
            "children": [
                {
                    "kind": "container",
                    "target": {"name": "Orion field", "ra": target.ra, "dec": target.dec},
                    "children": [
                        {"kind": "slew"},
                        {"kind": "autofocus"},
                        {
                            "kind": "expose",
                            "batch": 1,
                            "rows": [
                                {"filter": names[0], "exposure": 1, "count": 2},
                                {"filter": names[1], "exposure": 1, "count": 1},
                            ],
                        },
                    ],
                }
            ]
        },
        "end": {"children": [{"kind": "park"}, {"kind": "warm", "ramp": 0}]},
    }
    assert api.put("/api/sequences/two", json=sequence).status_code == 204
    response = api.post("/api/sequences/two/start")
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]

    # The rig is the sequence's while it runs.
    response = api.post("/api/filter-wheel/select", json={"slot": 1})
    assert response.status_code == 409
    assert "sequence" in response.json()["detail"]

    wait(api, finished(job_id), timeout=300)
    current = state(api)
    AppState.model_validate(current)
    job, run = current["jobs"][job_id], current["sequence"]["run"]
    assert job["state"] == "succeeded", (job, current["sequence"]["events"])
    assert run["outcome"] == "completed"
    [plan] = run["plans"].values()
    assert [r["done"] for r in plan["rows"]] == [2, 1]
    frames = [e for e in current["sequence"]["events"] if e["kind"] == "frame"]
    assert [e["message"].split()[0] for e in frames] == [names[0], names[1], names[0]]
    assert current["mount"]["parked"]
    assert current["autofocus"]["state"] == "succeeded"

    saved = api.get("/api/frames", params={"target": "Orion field"}).json()
    assert len(saved) == 3
    assert {f["filter"] for f in saved} == set(names)
