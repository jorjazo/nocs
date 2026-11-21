# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The Video view against the CCD simulator: stream, preview, region, a SER recording."""

import json
import os
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.config import Settings

pytestmark = [pytest.mark.indi, pytest.mark.slow]

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
DRIVER_UPLOADS = "/run/indi/uploads"
"""The dev container's shared directory, as indiserver sees it."""


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {k: current.get(k) for k in ("video", "jobs")}
        time.sleep(0.1)


@pytest.fixture(scope="module")
def shared() -> Path:
    """A directory below the one the simulators' container shares, for the SER files the
    driver writes (NOCS_TEST_INDI_UPLOADS)."""
    value = os.environ.get("NOCS_TEST_INDI_UPLOADS")
    if not value:
        pytest.skip("NOCS_TEST_INDI_UPLOADS not set (e.g. ../dev/.run/uploads)")
    return Path(value)


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory, shared: Path) -> Iterator[TestClient]:
    value = os.environ.get("NOCS_TEST_INDI")
    if not value:
        pytest.skip("NOCS_TEST_INDI not set")
    host, _, port = value.rpartition(":")
    storage = shared / f"video-test-{uuid.uuid4().hex[:8]}"
    storage.mkdir()
    settings = Settings(
        indi_host=host,
        indi_port=int(port),
        config_dir=tmp_path_factory.mktemp("config"),
        data_dir=tmp_path_factory.mktemp("data"),
        storage_dir=storage,
        indi_shared_dir=Path(DRIVER_UPLOADS),
        indi_shared_dir_local=shared,
    )
    profile = {**SIMULATORS, "devices": dict(SIMULATORS["devices"])}
    profile["devices"].pop("weather")
    # The driver writes the SER files as the container's user, which is not this one
    # in CI: the folders nocsd makes for them must let it.
    umask = os.umask(0)
    storage.chmod(0o777)
    try:
        with TestClient(create_app(settings)) as client:
            pair_owner(client)
            response = client.put("/api/storage/destination", json={"destination": "internal"})
            assert response.status_code == 204, response.text
            assert client.put("/api/profiles/sim", json=profile).status_code == 204
            response = client.post("/api/equipment/connect", json={"profile": "sim"})
            assert response.status_code == 202
            wait(client, lambda s: "main_camera" in s.get("cameras", {}), timeout=60)
            yield client
            client.post("/api/video/stop")
            wait(client, lambda s: s["video"]["job"] is None)
    finally:
        os.umask(umask)
        for path in sorted(storage.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        storage.rmdir()


def frame(api: TestClient, after: int = 0) -> tuple[int, bytes]:
    response = api.get("/api/video/frame", params={"after": after})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    return int(response.headers["x-frame"]), response.content


def test_the_camera_can_stream(api: TestClient) -> None:
    video = state(api)["cameras"]["main_camera"]["video"]
    assert video is not None
    assert video["depths"]


def test_recording_needs_the_stream(api: TestClient) -> None:
    assert api.post("/api/video/record", json={"seconds": 1}).status_code == 409


def test_stream_preview_region_and_recording(api: TestClient) -> None:
    camera = state(api)["cameras"]["main_camera"]
    sensor = camera["sensor"]
    depths = camera["video"]["depths"]
    response = api.put("/api/video/settings", json={"exposure": 0.01, "depth": depths[0]})
    assert response.status_code == 204, response.text
    response = api.post("/api/video/start")
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    wait(api, lambda s: s["video"]["streaming"] and s["video"]["frame"] is not None)
    seq, jpeg = frame(api)
    assert jpeg.startswith(b"\xff\xd8")
    newer, _ = frame(api, seq)
    assert newer > seq
    current = state(api)["video"]["frame"]
    assert (current["frame_width"], current["frame_height"]) == (sensor["width"], sensor["height"])

    # Explore cannot take the camera meanwhile.
    response = api.post("/api/cameras/main_camera/loop", json={"exposure": 1})
    assert response.status_code == 409, response.text

    # A region the camera's rules change: even start, a width in eights.
    region = {"x": 101, "y": 99, "width": 323, "height": 241}
    assert api.put("/api/video/settings", json={"region": region}).status_code == 204
    fitted = {"x": 100, "y": 98, "width": 320, "height": 240}
    assert state(api)["video"]["region"] == fitted
    wait(
        api,
        lambda s: (
            (f := s["video"]["frame"]) is not None
            and (f["frame_width"], f["frame_height"]) == (320, 240)
        ),
    )

    response = api.post("/api/video/record", json={"frames": 30})
    assert response.status_code == 202, response.text
    recording_id = response.json()["id"]
    # Nothing moves the image while it records.
    assert api.put("/api/video/settings", json={"exposure": 0.02}).status_code == 409
    wait(api, lambda s: s["video"]["recording"] is None and s["video"]["recordings"])
    entry = state(api)["video"]["recordings"][0]
    assert entry["id"] == recording_id
    # The simulator records at its sensor's depth, whatever the preview's.
    assert (entry["width"], entry["height"], entry["depth"]) == (320, 240, depths[0])
    # INDI's stream manager sometimes stops one frame short of a count.
    assert 29 <= entry["frames"] <= 30
    assert entry["path"].endswith(".ser")
    assert "/Video/" in entry["path"]
    assert Path(entry["file"]).is_file()

    response = api.get(f"/api/video/recordings/{recording_id}")
    assert response.status_code == 200
    assert response.content[:14].rstrip(b"\0").endswith(b"RECORDER")

    # Back to the whole sensor: the simulator's cut goes too.
    assert api.put("/api/video/settings", json={"region": "full"}).status_code == 204
    wait(
        api,
        lambda s: (
            (f := s["video"]["frame"]) is not None
            and (f["frame_width"], f["frame_height"]) == (sensor["width"], sensor["height"])
        ),
    )

    assert api.post("/api/video/stop").status_code == 204
    wait(api, lambda s: s["jobs"][job]["state"] != "running" and not s["video"]["streaming"])
    # The camera is left as it was: the whole sensor.
    region = state(api)["cameras"]["main_camera"]["region"]
    assert (region["width"], region["height"]) == (sensor["width"], sensor["height"])

    assert api.delete(f"/api/video/recordings/{recording_id}").status_code == 204
    assert not Path(entry["file"]).exists()
    assert state(api)["video"]["recordings"] == []
