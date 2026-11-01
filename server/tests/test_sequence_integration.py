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
from simfocus import APERTURE, FOCAL_LENGTH, FOCUSER, ORION

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


def set_property(api: TestClient, device: str, name: str, values: dict[str, Any]) -> None:
    response = api.post(f"/api/indi/devices/{device}/properties/{name}", json={"values": values})
    assert response.status_code == 202, response.text


def test_autofocus_follows_the_temperature_and_the_stars(api: TestClient) -> None:
    if state(api)["mount"]["parked"]:
        assert api.post("/api/mount/unpark").status_code == 204
    target = jnow_to_j2000(*ORION, datetime.now(UTC))
    trigger = {"kind": "autofocus", "temperature_change": 1, "hfr_increase": 0.3, "hfr_frames": 2}
    sequence = {
        "name": "Triggers",
        "targets": {
            "children": [
                {
                    "kind": "container",
                    "target": {"name": "Orion field", "ra": target.ra, "dec": target.dec},
                    "triggers": [trigger],
                    "children": [
                        {"kind": "slew"},
                        {"kind": "autofocus"},
                        # More frames than the triggers need: the test stops the run
                        # after the third autofocus, however late its steps land.
                        {"kind": "expose", "rows": [{"exposure": 1, "count": 30}]},
                    ],
                }
            ]
        },
    }
    assert api.put("/api/sequences/triggers", json=sequence).status_code == 204
    response = api.post("/api/sequences/triggers/start")
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]

    def events(s: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        return [e for e in s["sequence"]["events"] if e["kind"] == kind]

    def focused(s: dict[str, Any]) -> list[dict[str, Any]]:
        return [e for e in events(s, "action") if e["message"] == "autofocus"]

    def attempts(s: dict[str, Any]) -> int:
        """Autofocus runs, those skipped after failing their checks included."""
        skipped = [e for e in events(s, "skipped") if e["message"] == "autofocus"]
        return len(focused(s)) + len(skipped)

    temperature = state(api)["focuser"]["temperature"]
    try:
        # Two frames after the first run, the focuser warms by 2 °C.
        wait(api, lambda s: len(events(s, "frame")) >= 2 and len(focused(s)) == 1, timeout=180)
        set_property(api, FOCUSER, "FOCUS_TEMPERATURE", {"TEMPERATURE": temperature + 2})
        wait(api, lambda s: len(focused(s)) == 2, timeout=180)
        # Two frames after that run, someone knocks the focuser out of focus: 10000
        # steps make the stars ~50 % larger (the trigger asks for 30 %) and stay within
        # reach of a sweep; 15000 sometimes left too few stars for one to succeed.
        start = len(events(state(api), "frame"))
        wait(api, lambda s: len(events(s, "frame")) >= start + 2, timeout=60)
        position = state(api)["focuser"]["position"]
        set_property(
            api, FOCUSER, "ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": position + 10000}
        )
        wait(api, lambda s: attempts(s) == 3, timeout=240)
        assert api.post("/api/sequence/stop", json={"run_end": False}).status_code == 204
        wait(api, finished(job_id), timeout=60)
    finally:
        set_property(api, FOCUSER, "FOCUS_TEMPERATURE", {"TEMPERATURE": temperature})

    current = state(api)
    assert current["jobs"][job_id]["state"] == "succeeded", current["sequence"]["events"]
    reasons = [e["message"] for e in events(current, "trigger")]
    assert len(reasons) == 2, reasons
    assert reasons[0].startswith("autofocus: temperature +2.0")
    assert reasons[1].startswith("autofocus: HFR +")
    # Each trigger brought a run. A run that fails its quality checks is skipped by the
    # `focus` policy (ADR 0032): what this test checks is that the triggers asked.
    runs = focused(current)
    assert attempts(current) == 3, current["sequence"]["events"]
    assert runs[0]["data"]["position"] is not None
    if len(runs) == 3:
        # The last run brought the focuser back near where the first one put it.
        assert abs(runs[2]["data"]["position"] - runs[0]["data"]["position"]) < 4000


def orion_plan(name: str, count: int, **sequence: Any) -> dict[str, Any]:
    target = jnow_to_j2000(*ORION, datetime.now(UTC))
    return {
        "name": name,
        "targets": {
            "children": [
                {
                    "kind": "container",
                    "target": {"name": "Orion field", "ra": target.ra, "dec": target.dec},
                    "children": [
                        {"kind": "slew"},
                        {"kind": "expose", "rows": [{"exposure": 1, "count": count}]},
                    ],
                }
            ]
        },
        **sequence,
    }


def test_frames_under_clouds_are_taken_again(api: TestClient) -> None:
    if state(api)["mount"]["parked"]:
        assert api.post("/api/mount/unpark").status_code == 204
    clouds = {"clouds": {"retries": 5, "wait": 3}}
    response = api.put("/api/sequences/clouds", json=orion_plan("Clouds", 3, recovery=clouds))
    assert response.status_code == 204, response.text
    response = api.post("/api/sequences/clouds/start")
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]

    def events(s: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        return [e for e in s["sequence"]["events"] if e["kind"] == kind]

    try:
        wait(api, lambda s: len(events(s, "frame")) >= 1, timeout=120)
        set_property(api, "CCD Simulator", "SIMULATOR_SETTINGS", {"SIM_LIMITINGMAG": 0})
        wait(api, lambda s: any(e["data"].get("kind") == "clouds" for e in events(s, "failed")))
    finally:
        set_property(api, "CCD Simulator", "SIMULATOR_SETTINGS", {"SIM_LIMITINGMAG": 17})
    wait(api, finished(job_id), timeout=120)
    current = state(api)
    assert current["jobs"][job_id]["state"] == "succeeded", current["sequence"]["events"]
    assert len(events(current, "frame")) == 3
    failed = events(current, "failed")
    assert failed
    assert {e["data"]["kind"] for e in failed} == {"clouds"}
    assert {e["data"]["then"] for e in failed} == {"retry"}


@pytest.fixture
def restartable(tmp_path: Path) -> tuple[Settings, dict[str, Any]]:
    value = os.environ.get("NOCS_TEST_INDI")
    if not value:
        pytest.skip("NOCS_TEST_INDI not set")
    host, _, port = value.rpartition(":")
    settings = Settings(
        indi_host=host,
        indi_port=int(port),
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    roles = {"main_camera", "mount"}
    profile = {
        **SIMULATORS,
        "devices": {k: v for k, v in SIMULATORS["devices"].items() if k in roles},
        "imaging": {"focal_length": FOCAL_LENGTH, "aperture": APERTURE},
        "site": {
            "name": "Sim",
            "latitude": LATITUDE,
            "longitude": longitude_for_orion(datetime.now(UTC)),
        },
    }
    return settings, profile


def outcome(s: dict[str, Any]) -> str | None:
    run = s["sequence"]["run"]
    return None if run is None else run["outcome"]


def report_clock(client: TestClient) -> None:
    now = datetime.now(UTC).isoformat()
    response = client.post("/api/clock", json={"utc": now, "utc_offset": 0})
    assert response.status_code == 200, response.text


def test_a_restarted_nocsd_finishes_the_run(restartable: tuple[Settings, dict[str, Any]]) -> None:
    settings, profile = restartable
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        assert client.put("/api/profiles/restart", json=profile).status_code == 204
        response = client.post("/api/equipment/connect", json={"profile": "restart"})
        assert response.status_code == 202, response.text
        wait(client, lambda s: s.get("mount") is not None and "main_camera" in s["cameras"])
        report_clock(client)
        wait(client, lambda s: s["mount"]["site_sent"] and s["mount"]["time_sent"])
        if state(client)["mount"]["parked"]:
            assert client.post("/api/mount/unpark").status_code == 204
        pointing = {
            "ra": state(client)["mount"]["ra_j2000"],
            "dec": state(client)["mount"]["dec_j2000"],
        }
        assert client.put("/api/sequences/night", json=orion_plan("Night", 4)).status_code == 204
        assert client.post("/api/sequences/night/start").status_code == 202
        wait(
            client,
            lambda s: sum(e["kind"] == "frame" for e in s["sequence"]["events"]) >= 2,
            timeout=120,
        )
        run = state(client)["sequence"]["run"]["run"]
    # nocsd went away mid-run (the app stopped); it starts again on the same disks.
    try:
        with TestClient(create_app(settings)) as client:
            pair_owner(client)
            report_clock(client)  # a phone, NTP or a GPS: the mount needs the time
            wait(client, lambda s: outcome(s) == "completed", timeout=180)
            current = state(client)
            again = current["sequence"]["run"]
            assert (again["run"], again["restarts"]) == (run, 1)
            [plan] = again["plans"].values()
            assert plan["rows"][0]["done"] == 4
            frames = [e for e in current["sequence"]["events"] if e["kind"] == "frame"]
            assert 2 <= len(frames) <= 3  # the frame in progress at the restart is taken again
    finally:
        with TestClient(create_app(settings)) as client:
            pair_owner(client)
            client.post("/api/equipment/connect", json={"profile": "restart"})
            wait(client, lambda s: s.get("mount") is not None)
            report_clock(client)
            wait(client, lambda s: s["mount"]["time_sent"])
            goto = {"frame": "j2000", **pointing, "force": True}
            response = client.post("/api/mount/goto", json=goto)
            if response.status_code == 202:
                wait(client, finished(response.json()["job"]))
