# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Camera settings, cooling and exposures through the API, against the simulators."""

import io
import json
import os
import time
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from fastapi.testclient import TestClient

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings

pytestmark = pytest.mark.indi

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
SMALL = {"x": 0, "y": 0, "width": 320, "height": 240}
SITE = {"name": "Lab", "latitude": -30.2, "longitude": -70.7, "elevation": 2400}
_fits: Any = fits  # untyped library; see nocs.imaging.pipeline


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {k: current.get(k) for k in ("cameras", "jobs")}
        time.sleep(0.1)


def camera(api: TestClient, role: str = "main_camera") -> dict[str, Any]:
    return state(api)["cameras"][role]


def job(api: TestClient, job_id: str) -> dict[str, Any]:
    return state(api)["jobs"][job_id]


def finished(job_id: str) -> Callable[[dict[str, Any]], bool]:
    return lambda s: s["jobs"][job_id]["state"] != "running"


# The dev container's frame upload directory, as indiserver sees it.
DRIVER_UPLOADS = "/run/indi/uploads"


@pytest.fixture(scope="module", params=["blob", "local"])
def transfer(request: pytest.FixtureRequest) -> Path | None:
    """How frames reach nocsd (ADR 0012); ``local`` needs NOCS_TEST_INDI_UPLOADS."""
    if request.param == "blob":
        return None
    value = os.environ.get("NOCS_TEST_INDI_UPLOADS")
    if not value:
        pytest.skip("NOCS_TEST_INDI_UPLOADS not set (e.g. ../dev/.run/uploads)")
    return Path(value)


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory, transfer: Path | None) -> Path:
    return tmp_path_factory.mktemp("data")


@pytest.fixture(scope="module")
def api(
    tmp_path_factory: pytest.TempPathFactory, data_dir: Path, transfer: Path | None
) -> Iterator[TestClient]:
    value = os.environ.get("NOCS_TEST_INDI")
    if not value:
        pytest.skip("NOCS_TEST_INDI not set")
    host, _, port = value.rpartition(":")
    settings = Settings(
        indi_host=host,
        indi_port=int(port),
        config_dir=tmp_path_factory.mktemp("config"),
        data_dir=data_dir,
        indi_upload_dir=Path(DRIVER_UPLOADS) if transfer else None,
        indi_upload_dir_local=transfer,
    )
    profile = {**SIMULATORS, "devices": dict(SIMULATORS["devices"]), "site": SITE}
    profile["devices"].pop("power_box")  # needs the FIFO; not relevant here
    with TestClient(create_app(settings)) as client:
        # Never a drive that happens to be mounted on the test machine.
        response = client.put("/api/storage/destination", json={"destination": "internal"})
        assert response.status_code == 204, response.text
        assert client.put("/api/profiles/sim", json=profile).status_code == 204
        assert client.post("/api/equipment/connect", json={"profile": "sim"}).status_code == 202
        wait(client, lambda s: s["equipment"]["connection"] == "connected", timeout=60)
        wait(client, lambda s: {"main_camera", "guide_camera"} <= set(s.get("cameras", {})))
        try:
            yield client
        finally:
            # Leave the shared simulator as other tests expect it.
            client.post(
                "/api/cameras/main_camera/settings",
                json={"binning": 1, "region": "full", "frame_type": "light"},
            )
            client.post("/api/cameras/main_camera/cooling", json={"on": False})


def test_camera_state(api: TestClient) -> None:
    current = state(api)
    AppState.model_validate(current)
    main = current["cameras"]["main_camera"]
    assert main["device"] == "CCD Simulator"
    assert main["sensor"]["width"] > 0
    assert main["gain"] is not None
    assert main["gain_range"]["max"] > main["gain_range"]["min"]
    assert main["exposing"] is False
    assert current["cameras"]["guide_camera"]["device"] == "Guide Simulator"

    # Connecting pointed the camera at the rig's devices and optics (FITS headers).
    properties = current["indi"]["devices"]["CCD Simulator"]["properties"]
    snooped = {k: e["value"] for k, e in properties["ACTIVE_DEVICES"]["elements"].items()}
    assert snooped["ACTIVE_TELESCOPE"] == "Telescope Simulator"
    assert snooped["ACTIVE_FOCUSER"] == "Focuser Simulator"
    assert snooped["ACTIVE_FILTER"] == "Filter Simulator"
    assert properties["SCOPE_INFO"]["elements"]["FOCAL_LENGTH"]["value"] == 250


def test_settings(api: TestClient) -> None:
    response = api.post(
        "/api/cameras/main_camera/settings",
        json={"gain": 120, "offset": 10, "binning": 2, "region": SMALL, "frame_type": "dark"},
    )
    assert response.status_code == 204, response.text
    wait(api, lambda s: s["cameras"]["main_camera"]["region"] == SMALL)
    main = camera(api)
    assert (main["gain"], main["offset"], main["binning"], main["frame_type"]) == (
        120,
        10,
        [2, 2],
        "dark",
    )


def test_invalid_settings(api: TestClient) -> None:
    too_big = {"x": 0, "y": 0, "width": 100000, "height": 10}
    assert (
        api.post("/api/cameras/main_camera/settings", json={"region": too_big}).status_code == 422
    )
    assert api.post("/api/cameras/main_camera/settings", json={"gain": 1e9}).status_code == 422
    assert api.post("/api/cameras/main_camera/settings", json={"binning": 99}).status_code == 422
    assert api.post("/api/cameras/telescope/settings", json={}).status_code == 422


def test_expose_and_save(api: TestClient, data_dir: Path) -> None:
    api.post("/api/cameras/main_camera/settings", json={"region": SMALL, "binning": 1})
    assert api.put("/api/storage/target", json={"target": "M 31"}).status_code == 204
    response = api.post(
        "/api/cameras/main_camera/expose", json={"exposure": 1, "frame_type": "light"}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(api, finished(job_id))
    result = job(api, job_id)
    assert result["state"] == "succeeded", result
    frame = result["result"]
    assert frame["destination"] == "internal"
    relative = Path(frame["path"])
    night, kind, target, filter = relative.parts[:4]
    assert (kind, target) == ("Light", "M_31")
    assert filter  # from the simulated wheel, through the FITS header
    path = data_dir / "NOCS" / relative
    assert path.read_bytes().startswith(b"SIMPLE")
    assert (frame["exposure"], frame["frame_type"], frame["size"]) == (
        1,
        "light",
        path.stat().st_size,
    )
    with _fits.open(path) as hdus:
        header = hdus[0].header
        assert (header["OBJECT"], header["SITENAME"], header["FILTER"]) == ("M 31", "Lab", filter)
        assert header["SWCREATE"].startswith("NOCS ")
        assert header["FOCALLEN"] == 250
    assert camera(api)["last_frame"] == frame
    current = state(api)
    AppState.model_validate(current)
    assert current["storage"]["target"] == "M 31"
    preview = camera(api)["preview"]
    assert (preview["exposure"], preview["frame_type"]) == (1, "light")
    assert (preview["width"], preview["height"]) == (320, 240)
    assert len(preview["histogram"]) == 256
    response = api.get(preview["url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8")  # JPEG
    assert "immutable" in response.headers["cache-control"]
    assert api.get("/api/previews/" + "0" * 32 + ".jpg").status_code == 404

    # In the catalog, with the worker's metrics.
    [record] = api.get("/api/frames", params={"limit": 1}).json()
    assert (record["id"], record["path"], record["target"], record["night"]) == (
        frame["id"],
        frame["path"],
        "M 31",
        night,
    )
    assert record["available"] is True
    assert record["stars"] == preview["stars"]
    assert record["hfr"] == preview["hfr"]

    # Downloads: the file, resumable, and the night as a zip.
    download = api.get(record["url"])
    assert download.status_code == 200
    assert download.content == path.read_bytes()
    assert download.headers["content-type"] == "application/fits"
    assert path.name in download.headers["content-disposition"]
    part = api.get(record["url"], headers={"Range": "bytes=0-5"})
    assert (part.status_code, part.content) == (206, b"SIMPLE")
    assert api.get("/api/frames/999999/file").status_code == 404

    [info] = [n for n in api.get("/api/nights").json() if n["night"] == night]
    assert info["frames"] >= 1
    archive = api.get(info["zip_url"], params={"type": "light", "target": "M 31"})
    assert archive.status_code == 200
    assert int(archive.headers["content-length"]) == len(archive.content)
    assert f"NOCS_{night}_light_M_31.zip" in archive.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert frame["path"] in z.namelist()
        assert z.read(frame["path"]) == path.read_bytes()
    assert api.get("/api/nights/999999/zip").status_code == 404


def test_storage_commands(api: TestClient) -> None:
    assert api.put("/api/storage/destination", json={"destination": "nope"}).status_code == 409
    assert api.put("/api/storage/template", json={"template": "{nope}"}).status_code == 422
    assert api.put("/api/storage/target", json={"target": "///"}).status_code == 422
    assert api.get("/api/frames", params={"type": "nope"}).status_code == 422
    # Guide camera frames are previews only.
    guide = api.post("/api/cameras/guide_camera/expose", json={"exposure": 0.1, "save": True})
    assert guide.status_code == 422


def test_busy_camera_refuses_commands_and_cancel_aborts(api: TestClient) -> None:
    job_id = api.post("/api/cameras/main_camera/expose", json={"exposure": 30}).json()["job"]
    wait(api, lambda s: s["cameras"]["main_camera"]["exposing"])
    busy = api.post("/api/cameras/main_camera/settings", json={"gain": 100})
    assert busy.status_code == 409
    assert job_id in busy.json()["detail"]
    assert api.post("/api/cameras/main_camera/expose", json={"exposure": 1}).status_code == 409
    # The guide camera is a different resource.
    guide = api.post("/api/cameras/guide_camera/expose", json={"exposure": 0.1, "save": False})
    assert guide.status_code == 202

    assert api.post(f"/api/jobs/{job_id}/cancel").status_code == 202
    wait(api, finished(job_id))
    assert job(api, job_id)["state"] == "cancelled"
    wait(api, lambda s: not s["cameras"]["main_camera"]["exposing"], timeout=10)
    assert api.post(f"/api/jobs/{job_id}/cancel").status_code == 409
    assert api.post("/api/jobs/nope/cancel").status_code == 404

    guide_job = guide.json()["job"]
    wait(api, finished(guide_job))
    assert job(api, guide_job)["state"] == "succeeded"
    assert job(api, guide_job)["result"]["path"] is None


def test_cooling(api: TestClient) -> None:
    response = api.post(
        "/api/cameras/main_camera/cooling", json={"on": True, "target": -10, "ramp": 2}
    )
    assert response.status_code == 204, response.text
    wait(api, lambda s: s["cameras"]["main_camera"]["ramp"] == 2)
    assert camera(api)["target"] == -10
    assert api.post("/api/cameras/main_camera/cooling", json={"on": True}).status_code == 422
    assert api.post("/api/cameras/main_camera/cooling", json={"on": False}).status_code == 204
    assert camera(api)["target"] is None


def test_loop_makes_previews_and_keeps_nothing(
    api: TestClient, data_dir: Path, transfer: Path | None
) -> None:
    api.post("/api/cameras/main_camera/settings", json={"region": SMALL, "binning": 1})
    before = camera(api)["preview"]
    saved = sorted((data_dir / "NOCS").rglob("*.fits"))
    response = api.post("/api/cameras/main_camera/loop", json={"exposure": 0.2})
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    seen: set[str] = set()

    def new_previews(s: dict[str, Any]) -> bool:
        preview = s["cameras"]["main_camera"]["preview"]
        if preview is not None and preview != before:
            seen.add(preview["url"])
        return len(seen) >= 3

    wait(api, new_previews)
    assert job(api, job_id)["message"].startswith("frame ")
    assert api.post("/api/cameras/main_camera/expose", json={"exposure": 1}).status_code == 409
    assert api.post(f"/api/jobs/{job_id}/cancel").status_code == 202
    wait(api, finished(job_id))
    assert job(api, job_id)["state"] == "cancelled"
    # Loop frames are analysed and then deleted, never kept. A driver may still save
    # the frame that was downloading when the loop stopped; the next exposure of
    # that camera clears it.
    time.sleep(1)
    assert sorted((data_dir / "NOCS").rglob("*.fits")) == saved
    last = api.post("/api/cameras/main_camera/expose", json={"exposure": 0.1, "save": False})
    wait(api, finished(last.json()["job"]))
    for directory in (data_dir / "incoming", transfer):
        if directory is not None:
            assert not list(directory.glob("main_camera_*")), directory
