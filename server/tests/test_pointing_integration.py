# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Solve and sync with the simulators and the real ASTAP.

The telescope simulator's mount model gives it a pointing error: its index errors
(``MOUNT_MODEL``, arcminutes) shift where the CCD simulator renders the sky from where
the mount says it points. A sync adds a point to the simulator's alignment model,
after which it reports the position the sync gave (INDI 2.2.5; only once its
alignment was initialised, here by clearing it).

With D05 only some of the simulator's 5 s frames of a sparse field solve, fewer of
its 10 s frames (the faint stars it adds do not help) and none of dense fields; one
that fails keeps failing until the frame changes, and some runs found no frame that
solved even over the whole sky (on a laptop, 2026-10-31; CI solved test_solving's
frames). Solves are therefore retried with the frame changed, and the test is
skipped, not failed, when none solves.
"""

import json
import math
import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.config import Settings
from nocs.solving import separation

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
SITE = {"name": "Lab", "latitude": -30.2, "longitude": -70.7, "elevation": 2400}
EXPOSURE = 5.0
FIELD = (0.0, -45.0)
"""J2000, far from the Milky Way (the simulator renders the sky whether or not it is
above the horizon)."""
ATTEMPTS = 6
TURN = 67
NUDGE = 0.4
"""How the frames change between attempts (degrees of rotation, and of Dec every
other attempt): the same frame failed again and again, a changed one often solved."""
INDEX_DEC = 20.0
INDEX_HA = 15.0
"""Arcminutes of the simulator's index errors."""


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {k: current.get(k) for k in ("mount", "jobs")}
        time.sleep(0.1)


def run(api: TestClient, response: Any) -> dict[str, Any]:
    """Wait for the job a request started; returns it."""
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(api, lambda s: s["jobs"][job_id]["state"] != "running", timeout=120)
    return state(api)["jobs"][job_id]


def solve(api: TestClient, sync: bool = False) -> dict[str, Any]:
    """A solve job that succeeded. While frames have no solution, the next is turned,
    and every other one taken a little further north (neither changes the offset)."""
    job: dict[str, Any] = {}
    attempt = 0
    try:
        for attempt in range(ATTEMPTS):
            rotate(api, attempt * TURN % 360)
            if attempt % 2:
                goto(api, FIELD[0], FIELD[1] + attempt * NUDGE)
            job = run(api, api.post("/api/solver/solve", json={"sync": sync}))
            failure = state(api)["solver"]["failure"]
            if job["state"] == "succeeded" or failure is None or failure["message"] != job["error"]:
                break
            assert failure["reason"] in {"no_solution", "no_stars"}, failure
    finally:
        rotate(api, 0)
    if job["state"] != "succeeded" and job["error"] == (state(api)["solver"]["failure"] or {}).get(
        "message"
    ):
        pytest.skip(f"none of {ATTEMPTS} frames of the CCD simulator solved: {job['error']}")
    assert job["state"] == "succeeded", (job["error"], state(api)["solver"])
    print(f"solved at attempt {attempt + 1}")
    return job


def goto(api: TestClient, ra: float, dec: float) -> None:
    """Go to J2000 ``ra``, ``dec`` and wait for the simulator to settle there."""
    job = run(
        api,
        api.post("/api/mount/goto", json={"frame": "j2000", "ra": ra, "dec": dec, "force": True}),
    )
    assert job["state"] == "succeeded", job
    # The simulator stays still afterwards: in CI a frame once landed 30° away.
    wait(api, lambda s: not s["mount"]["slewing"] and abs(s["mount"]["dec_j2000"] - dec) < 0.5)


def rotate(api: TestClient, degrees: float) -> None:
    response = api.post(
        "/api/indi/devices/CCD Simulator/properties/SIMULATOR_SETTINGS",
        json={"values": {"SIM_ROTATION": degrees}},
    )
    assert response.status_code == 202, response.text


def simulator(api: TestClient, name: str, values: dict[str, float | bool]) -> None:
    response = api.post(
        f"/api/indi/devices/Telescope Simulator/properties/{name}", json={"values": values}
    )
    assert response.status_code == 202, response.text


def mount_model(api: TestClient, dec: float, ha: float) -> None:
    """Set the index errors, and wait until the CCD simulator can see the sky they move
    to (``EQUATORIAL_PE``, which it follows, changes at the telescope's next poll)."""

    def telescope(s: dict[str, Any], name: str, element: str) -> float:
        properties = s["indi"]["devices"]["Telescope Simulator"]["properties"]
        return properties[name]["elements"][element]["value"]

    before = state(api)
    sky = telescope(before, "EQUATORIAL_PE", "DEC_PE")
    change = abs(dec - telescope(before, "MOUNT_MODEL", "MM_ID")) / 60
    simulator(api, "MOUNT_MODEL", {"MM_ID": dec, "MM_IH": ha})
    # Dec moves by the change of its index error, on either side of the pier.
    wait(api, lambda s: abs(abs(telescope(s, "EQUATORIAL_PE", "DEC_PE") - sky) - change) < 0.01)


def clear_alignment(api: TestClient) -> None:
    """Forget the simulator's syncs: each one adds an alignment point."""
    simulator(api, "ALIGNMENT_POINTSET_ACTION", {"CLEAR": True})
    simulator(api, "ALIGNMENT_POINTSET_COMMIT", {"ALIGNMENT_POINTSET_COMMIT": True})
    simulator(api, "ALIGNMENT_POINTSET_ACTION", {"APPEND": True})


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    value = os.environ.get("NOCS_TEST_INDI")
    if not value:
        pytest.skip("NOCS_TEST_INDI not set")
    astap = os.environ.get("NOCS_TEST_ASTAP")
    if not astap:
        pytest.skip("NOCS_TEST_ASTAP not set (e.g. ../dev/.astap/astap_cli)")
    database = os.environ.get("NOCS_TEST_ASTAP_DB")
    host, _, port = value.rpartition(":")
    settings = Settings(
        indi_host=host,
        indi_port=int(port),
        config_dir=tmp_path_factory.mktemp("config"),
        data_dir=tmp_path_factory.mktemp("data"),
        astap=Path(astap),
        astap_db=Path(database) if database else None,
    )
    devices = {k: v for k, v in SIMULATORS["devices"].items() if k in {"main_camera", "mount"}}
    profile = {**SIMULATORS, "devices": devices, "site": SITE}
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        assert client.put("/api/profiles/pointing", json=profile).status_code == 204
        assert (
            client.post("/api/equipment/connect", json={"profile": "pointing"}).status_code == 202
        )
        wait(client, lambda s: s.get("mount") is not None and "main_camera" in s.get("cameras", {}))
        utc = datetime.now(UTC).isoformat()
        assert client.post("/api/clock", json={"utc": utc, "utc_offset": -3}).status_code == 200
        if state(client)["mount"]["parked"]:
            assert client.post("/api/mount/unpark").status_code == 204
        # Also sets the simulator's alignment up: without that its first sync did nothing.
        clear_alignment(client)
        try:
            yield client
        finally:
            client.post("/api/mount/abort")
            mount_model(client, 0, 0)
            clear_alignment(client)


@pytest.mark.indi
def test_solve_measures_the_pointing_error_and_syncs(api: TestClient) -> None:
    api.post(
        "/api/cameras/main_camera/settings",
        json={"region": "full", "binning": 1, "frame_type": "light", "exposure": EXPOSURE},
    )
    goto(api, *FIELD)
    mount_model(api, INDEX_DEC, INDEX_HA)

    job = solve(api)
    assert job["kind"] == "solve"
    solved = state(api)["solver"]["last"]
    assert job["result"] == solved
    assert solved["synced"] is False
    mount = state(api)["mount"]
    assert solved["mount"]["ra"] == pytest.approx(mount["ra_j2000"], abs=1 / 3600)
    offset = solved["offset"]
    print(f"offset {offset}, solved in {solved['seconds']} s")
    # The signs depend on the side of the pier.
    cos_dec = math.cos(math.radians(mount["dec_j2000"]))
    assert abs(offset["dec"]) == pytest.approx(INDEX_DEC, abs=1)
    assert abs(offset["ra"]) == pytest.approx(INDEX_HA * cos_dec, abs=1)
    assert offset["angle"] == pytest.approx(math.hypot(INDEX_DEC, INDEX_HA * cos_dec), abs=1)

    # Without tracking the sky moves under the frame: no sync.
    assert api.put("/api/mount/tracking", json={"on": False}).status_code == 204
    try:
        response = api.post("/api/solver/sync")
        assert response.status_code == 409, response.text
        assert "not tracking" in response.json()["detail"]
    finally:
        assert api.put("/api/mount/tracking", json={"on": True}).status_code == 204

    # A sync to the solution: the mount says it points there.
    response = api.post("/api/solver/sync")
    assert response.status_code == 204, response.text
    assert state(api)["solver"]["last"]["synced"] is True
    assert api.post("/api/solver/sync").status_code == 409  # already synced
    wait(
        api,
        lambda s: (
            separation(s["mount"]["ra_j2000"], s["mount"]["dec_j2000"], solved["ra"], solved["dec"])
            < 1 / 60
        ),
        timeout=10,
    )

    # Solve and sync in one job, the way centring will.
    job = solve(api, sync=True)
    assert job["result"]["synced"] is True
    print(f"after the sync: offset {job['result']['offset']}")


def center(api: TestClient, **body: Any) -> dict[str, Any]:
    """A centring run. One that failed with frames that did not solve is tried again
    with the frame turned, and the target a little further north every other time:
    the run takes a frame that failed again without moving, which seldom helps."""
    result: dict[str, Any] = {}
    try:
        for attempt in range(ATTEMPTS):
            rotate(api, attempt * TURN % 360)
            dec = FIELD[1] + (attempt % 2) * NUDGE
            response = api.post("/api/solver/center", json={"ra": FIELD[0], "dec": dec, **body})
            assert response.status_code == 202, response.text
            job_id: str = response.json()["job"]

            def done(s: dict[str, Any], job_id: str = job_id) -> bool:
                return s["jobs"][job_id]["state"] != "running"

            wait(api, done, timeout=600)
            result = state(api)["centering"]
            assert result["job"] == job_id
            unsolved = any(a["failure"] is not None for a in result["attempts"])
            if result["state"] == "succeeded" or not unsolved:
                break
    finally:
        rotate(api, 0)
    if result["state"] != "succeeded" and any(a["failure"] for a in result["attempts"]):
        pytest.skip(f"frames of the CCD simulator kept failing in {ATTEMPTS} runs: {result}")
    errors = [round(a["error"]["angle"], 2) if a["error"] else None for a in result["attempts"]]
    print(f"centred ({body}): {result['state']}, errors {errors}")
    return result


@pytest.mark.indi
@pytest.mark.parametrize("method", ["sync", "offset"])
def test_center_corrects_the_pointing_error(api: TestClient, method: str) -> None:
    api.post(
        "/api/cameras/main_camera/settings",
        json={"region": "full", "binning": 1, "frame_type": "light", "exposure": EXPOSURE},
    )
    clear_alignment(api)
    # As 3.2's test does: the error appears when the index errors change once the mount
    # is on the field (changed just before the run's go to, a frame once landed on it).
    mount_model(api, 0, 0)
    goto(api, *FIELD)
    mount_model(api, INDEX_DEC, INDEX_HA)
    try:
        result = center(api, method=method, tolerance=1.0, attempts=5, settle=1.0)
    finally:
        clear_alignment(api)
    assert result["state"] == "succeeded", (result["error"], result)
    solved = [a for a in result["attempts"] if a["error"] is not None]
    cos_dec = math.cos(math.radians(FIELD[1]))
    expected = math.hypot(INDEX_DEC, INDEX_HA * cos_dec)
    assert solved[0]["error"]["angle"] == pytest.approx(expected, abs=1.5)
    assert solved[-1]["error"]["angle"] <= 1.0
    assert all(a["synced"] is (method == "sync") for a in solved)
    # The frame's centre, not just what the mount says, is on the target now.
    target = result["target"]
    final = solved[-1]["solution"]
    assert separation(final["ra"], final["dec"], target["ra"], target["dec"]) * 60 <= 1.0


@pytest.mark.indi
def test_solve_the_frame_on_screen(api: TestClient) -> None:
    """Live view's "Solve this frame": the frame behind the preview, without exposing."""
    api.post(
        "/api/cameras/main_camera/settings",
        json={"region": "full", "binning": 1, "frame_type": "light", "exposure": EXPOSURE},
    )
    goto(api, *FIELD)
    job: dict[str, Any] = {}
    for attempt in range(ATTEMPTS):
        rotate(api, attempt * TURN % 360)
        try:
            body = {"exposure": EXPOSURE, "save": False}
            shown = run(api, api.post("/api/cameras/main_camera/expose", json=body))
        finally:
            rotate(api, 0)
        assert shown["state"] == "succeeded", shown
        assert state(api)["cameras"]["main_camera"]["solvable"] is True
        job = run(api, api.post("/api/solver/solve", json={"frame": "last"}))
        assert job["resources"] == []
        if job["state"] == "succeeded":
            break
    else:
        pytest.skip(f"none of {ATTEMPTS} frames of the CCD simulator solved: {job['error']}")
    solved = state(api)["solver"]["last"]
    mount = state(api)["mount"]
    assert solved["mount"]["ra"] == pytest.approx(mount["ra_j2000"], abs=1 / 60)
    bad = api.post("/api/solver/solve", json={"frame": "last", "sync": True})
    assert bad.status_code == 422, bad.text
