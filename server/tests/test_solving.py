"""Plate solving: fields of view, ASTAP's results and how NOCS runs it (a fake ASTAP)."""

import math
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]

from nocs.devices import SensorInfo
from nocs.equipment import Optics
from nocs.solving import (
    Astap,
    Hint,
    SolveError,
    SolverService,
    downsample_for,
    field_of_view,
    separation,
)
from nocs.solving.astap import find_databases
from nocs.solving.solution import SolutionError, solution_from_ini
from nocs.state import StateStore

_fits: Any = fits
# The frame fixture is only a header, which astropy notices.
pytestmark = pytest.mark.filterwarnings("ignore:File may have been truncated")

# ASTAP's result for one of the maintainer's frames of M 8: ZWO ASI2600MC Duo at 384 mm,
# 6248 x 4176 px, rows top-down, camera angle 316° according to ASIAIR.
M8 = {
    "PLTSOLVD": "T",
    "CRPIX1": "3.1245000000000000E+003",
    "CRPIX2": "2.0885000000000000E+003",
    "CRVAL1": "2.7092749705717387E+002",
    "CRVAL2": "-2.3762873522508709E+001",
    "CD1_1": "-4.0649848345283222E-004",
    "CD1_2": "-3.8515240898436026E-004",
    "CD2_1": "3.8514657177160457E-004",
    "CD2_2": "-4.0636391327357750E-004",
}
ASI2600 = SensorInfo(
    width=6248, height=4176, pixel_size_x=3.76, pixel_size_y=3.76, bits_per_pixel=16
)

# A stand-in for astap_cli: writes the .ini that FAKE_ASTAP_INI holds (KEY=value lines)
# under the -o base name, unless the command has a hint and FAKE_ASTAP_HINT_FAILS is
# set; records its arguments and pid, and can sleep first.
FAKE = """\
import os, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_ASTAP_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
if "-h" in args:
    print("ASTAP astrometric solver version CLI-2026.09.01")
    sys.exit(0)
with open(os.environ["FAKE_ASTAP_PID"], "w") as f:
    f.write(str(os.getpid()))
time.sleep(float(os.environ.get("FAKE_ASTAP_SLEEP", "0")))
if "-ra" in args and os.environ.get("FAKE_ASTAP_HINT_FAILS"):
    sys.exit(1)
output = args[args.index("-o") + 1]
with open(output + ".ini", "w") as f:
    f.write(open(os.environ["FAKE_ASTAP_INI"]).read())
"""


@pytest.fixture
def fake_astap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Astap:
    executable = tmp_path / "astap_cli"
    executable.write_text(f"#!{sys.executable}\n{FAKE}")
    executable.chmod(executable.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "d05_0101.1476").touch()
    ini = tmp_path / "result.ini"
    ini.write_text("".join(f"{key}={value}\n" for key, value in M8.items()))
    monkeypatch.setenv("FAKE_ASTAP_INI", str(ini))
    monkeypatch.setenv("FAKE_ASTAP_LOG", str(tmp_path / "calls.log"))
    monkeypatch.setenv("FAKE_ASTAP_PID", str(tmp_path / "pid"))
    astap = Astap.find(executable)
    assert astap is not None
    return astap


@pytest.fixture
def frame(tmp_path: Path) -> Path:
    """A FITS file of the M 8 frame's size (the fake does not look at pixels)."""
    path = tmp_path / "frame.fits"
    header = _fits.Header()
    for key, value in (("SIMPLE", True), ("BITPIX", 16), ("NAXIS", 2)):
        header[key] = value
    header["NAXIS1"] = 6248
    header["NAXIS2"] = 4176
    header.tofile(path)  # only the header: the fake solver never reads pixels
    return path


def solver_state(store: StateStore) -> dict[str, Any]:
    return cast(dict[str, Any], store.snapshot()["solver"])


def calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "calls.log"
    lines = log.read_text().splitlines() if log.exists() else []
    return [line.split() for line in lines if "-h" not in line.split()]


def test_field_of_view() -> None:
    field = field_of_view(Optics(focal_length=384), ASI2600)
    assert field is not None
    assert field.scale == pytest.approx(2.0197, abs=1e-3)
    assert (field.width, field.height) == pytest.approx((3.505, 2.343), abs=1e-3)
    reduced = field_of_view(Optics(focal_length=480, reducer=0.8), ASI2600, binning=2)
    assert reduced is not None
    assert reduced.scale == pytest.approx(2 * field.scale)
    assert reduced.height == pytest.approx(field.height, rel=1e-3)
    assert field_of_view(Optics(focal_length=384), SensorInfo(0, 0, 0, 0, 16)) is None


def test_solution_from_astap() -> None:
    solution = solution_from_ini(M8, 6248, 4176)
    # CRPIX is the frame's centre, so the centre is CRVAL.
    assert solution.ra == pytest.approx(270.9275 / 15, abs=1e-5)
    assert solution.dec == pytest.approx(-23.7629, abs=1e-4)
    assert solution.scale == pytest.approx(2.0158, abs=1e-3)
    assert solution.fov == pytest.approx((3.499, 2.338), abs=1e-3)
    # ASIAIR's camera angle (316°) is 360° minus the position angle of the image's top.
    assert solution.rotation == pytest.approx(360 - 316.5, abs=0.5)
    assert not solution.mirrored  # a refractor shows the sky directly

    flipped = solution_from_ini(M8, 6248, 4176, bottom_up=True)
    assert flipped.rotation == pytest.approx((solution.rotation + 180) % 360)
    assert flipped.mirrored

    corners = solution.corners()
    assert len(corners) == 4
    diagonal = math.hypot(*solution.fov)
    for ra, dec in corners:
        assert separation(ra, dec, solution.ra, solution.dec) == pytest.approx(
            diagonal / 2, rel=0.01
        )


def test_incomplete_solution() -> None:
    with pytest.raises(SolutionError):
        solution_from_ini({"PLTSOLVD": "T", "CRVAL1": "1"}, 100, 100)


def test_downsample_from_star_size_and_frame_size() -> None:
    rows = 4176  # an ASI2600 frame
    assert downsample_for(None, rows) == 1
    assert downsample_for(math.nan, rows) == 1
    assert downsample_for(0.8, rows) == 1  # the simulators' sharp stars
    assert downsample_for(2.0, rows) == 1
    assert downsample_for(3.2, rows) == 2
    assert downsample_for(5.0, rows) == 2  # two steps of 1500 rows
    assert downsample_for(5.0, 6388) == 3  # an ASI6200 frame
    assert downsample_for(22.0, 6388) == 3  # a badly defocused one
    assert downsample_for(4.4, 1080) == 1  # small frames keep every pixel


def test_databases(tmp_path: Path) -> None:
    for name in ("d50_0101.1476", "d50_0102.1476", "g05_0101.1476", "readme.txt"):
        (tmp_path / name).touch()
    databases = find_databases(tmp_path)
    assert [d.name for d in databases] == ["D50", "G05"]
    astap = Astap(tmp_path / "astap_cli", tmp_path)
    assert astap.database_for(2.3) == databases[0]
    assert astap.database_for(10) == databases[1]
    assert astap.database_for(30) is None
    assert find_databases(tmp_path / "missing") == []


def test_command(tmp_path: Path) -> None:
    astap = Astap(Path("/opt/astap/astap_cli"), Path("/opt/astap"))
    hinted = astap.command(
        Path("f.fits"), Path("out"), fov=2.34, hint=Hint(18.0886, -23.76, 15), downsample=2
    )
    assert hinted[:13] == [
        *("/opt/astap/astap_cli", "-f", "f.fits", "-o", "out", "-d", "/opt/astap"),
        *("-z", "2", "-fov", "2.3400", "-speed", "slow"),
    ]
    assert hinted[13:] == ["-ra", "18.088600", "-spd", "66.240000", "-r", "15"]
    blind = astap.command(Path("f.fits"), Path("out"), fov=None, hint=None, downsample=1)
    assert blind[-6:] == ["-fov", "0", "-speed", "slow", "-r", "180"]


def test_finds_astap_next_to_its_databases(tmp_path: Path) -> None:
    assert Astap.find(tmp_path / "missing") is None
    executable = tmp_path / "astap_cli"
    executable.touch()
    (tmp_path / "d05_0101.1476").touch()
    astap = Astap.find(executable)
    assert astap is not None
    assert astap.database_dir == tmp_path
    assert [d.name for d in astap.databases] == ["D05"]


async def test_service_solves_and_publishes(fake_astap: Astap, frame: Path, tmp_path: Path) -> None:
    store = StateStore()
    service = SolverService(store, fake_astap)
    await service.start()
    solver = solver_state(store)
    assert solver["available"]
    assert solver["version"] == "CLI-2026.09.01"
    assert solver["databases"] == [{"name": "D05", "min_fov": 0.6, "max_fov": 6.0}]
    assert solver["last"] is None

    result = await service.solve(frame, fov=2.34, hint=Hint(18.09, -23.76), hfr=3.2)
    assert result.hinted
    assert result.downsample == 2
    assert result.solution.rotation == pytest.approx(43.5, abs=0.5)
    [command] = calls(tmp_path)
    assert command[command.index("-f") + 1] == str(frame)
    assert "-ra" in command

    last = solver_state(store)["last"]
    assert last["ra"] == pytest.approx(result.solution.ra)
    assert last["hinted"] is True
    assert solver_state(store)["solving"] is False


async def test_blind_after_the_hint_fails(
    fake_astap: Astap, frame: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ASTAP_HINT_FAILS", "1")
    service = SolverService(StateStore(), fake_astap)
    result = await service.solve(frame, fov=2.34, hint=Hint(6, 0))
    assert not result.hinted
    first, second = calls(tmp_path)
    assert "-ra" in first
    assert "-ra" not in second
    assert second[-2:] == ["-r", "180"]

    with pytest.raises(SolveError, match="no solution found"):
        await service.solve(frame, fov=2.34, hint=Hint(6, 0), blind=False)


async def test_refuses_fields_no_database_solves(fake_astap: Astap, frame: Path) -> None:
    service = SolverService(StateStore(), fake_astap)
    with pytest.raises(SolveError, match="no star database for a 12° field"):
        await service.solve(frame, fov=12, hint=None)


async def test_without_astap(frame: Path) -> None:
    store = StateStore()
    service = SolverService(store, None)
    await service.start()
    assert solver_state(store)["available"] is False
    with pytest.raises(SolveError, match="not installed"):
        await service.solve(frame, fov=2.34, hint=None)


async def test_cancelling_kills_astap(
    fake_astap: Astap, frame: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ASTAP_SLEEP", "30")
    store = StateStore()
    service = SolverService(store, fake_astap)
    pid_file = tmp_path / "pid"
    with anyio.move_on_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(lambda: service.solve(frame, fov=2.34, hint=None))
            while not pid_file.exists() or not pid_file.read_text():  # noqa: ASYNC110 (a file)
                await anyio.sleep(0.05)
            assert solver_state(store)["solving"] is True
            tasks.cancel_scope.cancel()
    assert not _alive(int(pid_file.read_text()))
    assert solver_state(store)["solving"] is False


async def test_timeout_kills_astap(
    fake_astap: Astap, frame: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ASTAP_SLEEP", "30")
    monkeypatch.setattr("nocs.solving.service.BLIND_TIMEOUT", 0.5)
    service = SolverService(StateStore(), fake_astap)
    start = time.monotonic()
    with pytest.raises(SolveError, match=r"no solution within 0\.5 s"):
        await service.solve(frame, fov=2.34, hint=None)
    assert time.monotonic() - start < 5
    assert not _alive(int((tmp_path / "pid").read_text()))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers; it is not running.
    status = Path(f"/proc/{pid}/stat")
    return status.exists() and status.read_text().split()[2] != "Z"
