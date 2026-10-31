# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Plate solving with the real ASTAP: real night frames, and frames of the simulators.

Real frames come from NOCS_TEST_FRAMES, a directory of FITS lights (symlinks are
fine) whose headers give the mount's position (RA/DEC in degrees: J2000 when
``EQUINOX = 2000``, else JNow as ASIAIR writes them), DATE-OBS, FOCALLEN and XPIXSZ,
and, from ASIAIR, its solved camera angle (ROTATOR).
"""

import json
import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.config import Settings
from nocs.imaging.pipeline import load, measure_stars
from nocs.mount.coords import jnow_to_j2000
from nocs.solving import Astap, Hint, SolverService, separation
from nocs.solving.service import image_info
from nocs.state import StateStore

_fits: Any = fits

SIMULATORS = json.loads(
    (Path(__file__).parents[2] / "dev" / "profiles" / "simulators.json").read_text()
)
EXPOSURE = 5.0
"""Seconds: at 2 s about half the simulator's frames had too few stars above its noise
for ASTAP with D05 (no solution); at 5 s every one solved."""
SITE = {"name": "Lab", "latitude": -30.2, "longitude": -70.7, "elevation": 2400}


@pytest.fixture
def astap(astap_paths: tuple[Path, Path | None]) -> Astap:
    found = Astap.find(*astap_paths)
    assert found is not None, astap_paths
    return found


def _real_frames() -> list[Path]:
    value = os.environ.get("NOCS_TEST_FRAMES")
    if not value:
        return []
    return sorted(p for p in Path(value).iterdir() if p.suffix.lower() in {".fit", ".fits"})


@pytest.mark.parametrize("path", _real_frames() or [None], ids=lambda p: p.name if p else "none")
async def test_real_frames(astap: Astap, path: Path | None) -> None:
    if path is None:
        pytest.skip("NOCS_TEST_FRAMES not set")
    header = _fits.getheader(path)
    ra, dec = header["RA"] / 15, header["DEC"]
    if header.get("EQUINOX") != 2000:
        taken = datetime.fromisoformat(header["DATE-OBS"]).replace(tzinfo=UTC)
        j2000 = jnow_to_j2000(ra, dec, taken)
        ra, dec = j2000.ra, j2000.dec
    scale = header["XPIXSZ"] / header["FOCALLEN"] * 206.265
    fov = header["NAXIS2"] * scale / 3600
    if astap.databases and astap.database_for(fov) is None:
        pytest.skip(f"no installed star database solves a {fov:.2f}° field")

    # The HFR, as the imaging worker measures it, chooses ASTAP's downsampling.
    _, hfr = measure_stars(load(str(path))[0], binned=True)
    service = SolverService(StateStore(), astap)
    start = time.monotonic()
    result = await service.solve(path, fov=fov, hint=Hint(ra, dec), hfr=hfr, blind=False)
    elapsed = time.monotonic() - start
    solution = result.solution
    print(f"{path.name}: HFR {hfr}, {elapsed:.2f} s, {solution}")
    # Where the mount thought it was: ASIAIR's 300 s frame of M 16 was 2' off.
    assert separation(solution.ra, solution.dec, ra, dec) < 5 / 60
    # Nominal focal lengths are a little off: the 1000 mm astrograph measures 1020 mm.
    assert solution.scale == pytest.approx(scale, rel=0.03)
    assert not solution.mirrored
    if "ROTATOR" in header:
        # ASIAIR's camera angle runs the other way from a position angle.
        difference = (360 - header["ROTATOR"] - solution.rotation + 180) % 360 - 180
        assert abs(difference) < 1.5

    # The whole sky (ASTAP starts the search from the header's position, if any).
    blind = await service.solve(path, fov=fov, hint=None, hfr=hfr)
    assert not blind.hinted
    assert separation(blind.solution.ra, blind.solution.dec, solution.ra, solution.dec) < 1 / 60


def state(api: TestClient) -> dict[str, Any]:
    return api.get("/api/state").json()["state"]


def wait(api: TestClient, condition: Callable[[dict[str, Any]], bool], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition(current := state(api)):
        assert time.monotonic() < deadline, {k: current.get(k) for k in ("mount", "jobs")}
        time.sleep(0.1)


def finished(job_id: str) -> Callable[[dict[str, Any]], bool]:
    return lambda s: s["jobs"][job_id]["state"] != "running"


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, Path]]:
    value = os.environ.get("NOCS_TEST_INDI")
    if not value:
        pytest.skip("NOCS_TEST_INDI not set")
    host, _, port = value.rpartition(":")
    data_dir = tmp_path_factory.mktemp("data")
    settings = Settings(
        indi_host=host,
        indi_port=int(port),
        config_dir=tmp_path_factory.mktemp("config"),
        data_dir=data_dir,
    )
    devices = {k: v for k, v in SIMULATORS["devices"].items() if k in {"main_camera", "mount"}}
    profile = {**SIMULATORS, "devices": devices, "site": SITE}
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        response = client.put("/api/storage/destination", json={"destination": "internal"})
        assert response.status_code == 204, response.text
        assert client.put("/api/profiles/solve", json=profile).status_code == 204
        assert client.post("/api/equipment/connect", json={"profile": "solve"}).status_code == 202
        wait(client, lambda s: s.get("mount") is not None and "main_camera" in s.get("cameras", {}))
        utc = datetime.now(UTC).isoformat()
        assert client.post("/api/clock", json={"utc": utc, "utc_offset": -3}).status_code == 200
        if state(client)["mount"]["parked"]:
            assert client.post("/api/mount/unpark").status_code == 204
        try:
            yield client, data_dir
        finally:
            client.post("/api/mount/abort")
            _rotate(client, 0)


def _rotate(api: TestClient, degrees: float) -> None:
    response = api.post(
        "/api/indi/devices/CCD Simulator/properties/SIMULATOR_SETTINGS",
        json={"values": {"SIM_ROTATION": degrees}},
    )
    assert response.status_code == 202, response.text


def _expose(api: TestClient, data_dir: Path) -> Path:
    response = api.post("/api/cameras/main_camera/expose", json={"exposure": EXPOSURE})
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(api, finished(job_id))
    job = state(api)["jobs"][job_id]
    assert job["state"] == "succeeded", job
    return data_dir / "NOCS" / job["result"]["path"]


@pytest.mark.indi
async def test_simulator_frames(api: tuple[TestClient, Path], astap: Astap) -> None:
    client, data_dir = api
    client.post(
        "/api/cameras/main_camera/settings",
        json={"region": "full", "binning": 1, "frame_type": "light"},
    )
    field = state(client)["cameras"]["main_camera"]["field"]
    assert field["focal_length"] == 250
    sensor = state(client)["cameras"]["main_camera"]["sensor"]
    assert field["scale"] == pytest.approx(sensor["pixel_size"] / 250 * 206.265)
    assert field["height"] == pytest.approx(sensor["height"] * field["scale"] / 3600)

    # Somewhere well above the horizon of a southern site, away from the pole.
    mount = state(client)["mount"]
    response = client.post(
        "/api/mount/goto",
        json={"frame": "j2000", "ra": mount["ra_j2000"], "dec": -45.0, "force": True},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]
    wait(client, finished(job_id))
    assert state(client)["jobs"][job_id]["state"] == "succeeded", state(client)["jobs"][job_id]
    # The simulator stays still afterwards: in CI a frame once landed 30° away.
    wait(client, lambda s: not s["mount"]["slewing"] and abs(s["mount"]["dec_j2000"] + 45) < 0.5)

    service = SolverService(StateStore(), astap)
    rotations: list[float] = []
    for degrees in (0, 30):
        _rotate(client, degrees)
        mount = state(client)["mount"]
        hint = Hint(mount["ra_j2000"], mount["dec_j2000"])
        path = _expose(client, data_dir)
        info = image_info(path)
        assert (info.width, info.height) == (sensor["width"], sensor["height"])
        result = await service.solve(path, fov=field["height"], hint=hint, hfr=None)
        solution = result.solution
        print(f"SIM_ROTATION {degrees}: {result.seconds:.2f} s, {solution}")
        assert result.hinted
        assert solution.scale == pytest.approx(field["scale"], rel=0.02)
        offset = separation(solution.ra, solution.dec, mount["ra_j2000"], mount["dec_j2000"])
        # The simulator renders the catalog at the mount's position (0.06' measured).
        assert offset < 1 / 60, offset * 60
        rotations.append(solution.rotation)
    turned = (rotations[1] - rotations[0] + 180) % 360 - 180
    assert abs(abs(turned) - 30) < 1, rotations
