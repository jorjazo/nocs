# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Polar alignment with the simulators and the real ASTAP (ADR 0034).

The telescope simulator's ``MOUNT_MODEL`` polar axis errors (``MM_ME`` up, ``MM_MA``
east on the sky, arcminutes) make it a misaligned mount; changing them while the job
runs is the user turning the altitude knob. Frames that do not solve skip the test, as in
test_pointing_integration.
"""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_pointing_integration import EXPOSURE, api, goto, simulator, state, wait

__all__ = ["api"]

START = (1.0, -45.0)
"""J2000."""
ERROR = (40.0, -25.0)
TURNED = (10.0, -25.0)
"""Only the altitude knob: the simulator's ``MM_MA`` moves the pole east without the
turn about the polar axis that a turn about the vertical brings (ADR 0034)."""


def polar_model(api: TestClient, up: float, east: float) -> None:
    simulator(api, "MOUNT_MODEL", {"MM_IH": 0, "MM_ID": 0, "MM_ME": up, "MM_MA": east})


@pytest.fixture
def misaligned(api: TestClient) -> Iterator[TestClient]:
    try:
        yield api
    finally:
        job = (state(api).get("polar_alignment") or {}).get("job")
        if job:
            api.post(f"/api/jobs/{job}/cancel")
            wait(api, lambda s: s["jobs"][job]["state"] != "running")
        polar_model(api, 0, 0)


def updates(api: TestClient) -> int:
    run = state(api).get("polar_alignment") or {}
    return len(run.get("updates", []))


@pytest.mark.indi
def test_polar_alignment_follows_the_knobs(misaligned: TestClient) -> None:
    api = misaligned
    api.post(
        "/api/cameras/main_camera/settings",
        json={"region": "full", "binning": 1, "frame_type": "light", "exposure": EXPOSURE},
    )
    # The fields that solve with D05 lie around 0h -45° (test_pointing_integration):
    # start at 1h, turn 15° (1 h) twice, east or west, as the job picks.
    goto(api, START[0], START[1])
    polar_model(api, *ERROR)
    time.sleep(2)

    response = api.post("/api/align/polar", json={"exposure": EXPOSURE, "step": 15})
    if response.status_code == 422:
        pytest.skip(f"the fields that solve are not up now: {response.json()['detail']}")
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]

    def measured_or_ended(s: dict[str, Any]) -> bool:
        return updates(api) >= 1 or s["jobs"][job_id]["state"] != "running"

    wait(api, measured_or_ended, timeout=300)
    run = state(api)["polar_alignment"]
    if run["state"] == "failed" and any(
        f["reason"] in {"no_solution", "no_stars"} for p in run["points"] for f in p["failures"]
    ):
        pytest.skip(f"the CCD simulator's frames did not solve: {run['error']}")
    assert run["state"] == "running", run["error"]
    print("rotation", run["rotation"], "axis", run["axis"])
    assert run["rotation"] == pytest.approx([15, 15], abs=0.5)
    # 15° turns grow the solves' error ~35 times in the fit (ADR 0034): a few arcminutes.
    assert (run["axis"]["altitude"], run["axis"]["azimuth"]) == pytest.approx(ERROR, abs=5)
    before = run["axis"]

    polar_model(api, *TURNED)
    count = updates(api)
    wait(api, lambda s: updates(api) >= count + 5, timeout=300)
    run = state(api)["polar_alignment"]
    for u in run["updates"]:
        print("update", u["taken"], u["axis"], u["knobs"], u["failure"])
    # A knob turn is read from one frame to the next, with no such growth.
    after = run["axis"]
    turned = (after["altitude"] - before["altitude"], after["azimuth"] - before["azimuth"])
    assert turned == pytest.approx((TURNED[0] - ERROR[0], TURNED[1] - ERROR[1]), abs=1.5)

    assert api.post("/api/align/polar/finish").status_code == 204
    wait(api, lambda s: s["jobs"][job_id]["state"] != "running", timeout=120)
    assert state(api)["jobs"][job_id]["state"] == "succeeded"
    assert abs(state(api)["mount"]["dec_j2000"] - START[1]) < 0.1  # back at the start
