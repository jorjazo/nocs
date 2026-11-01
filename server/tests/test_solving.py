"""Plate solving: fields of view, ASTAP's results and how NOCS runs it (a fake ASTAP)."""

import math
import os
import time
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from fakeastap import M8, calls, install_fake_astap, write_frame

from nocs.api.schemas import SolverState
from nocs.devices import SensorInfo
from nocs.equipment import Optics
from nocs.solving import (
    Astap,
    Failure,
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

ASI2600 = SensorInfo(
    width=6248, height=4176, pixel_size_x=3.76, pixel_size_y=3.76, bits_per_pixel=16
)


@pytest.fixture
def fake_astap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Astap:
    return install_fake_astap(tmp_path, monkeypatch)


@pytest.fixture
def frame(tmp_path: Path) -> Path:
    return write_frame(tmp_path / "frame.fits")


def solver_state(store: StateStore) -> dict[str, Any]:
    return cast(dict[str, Any], store.snapshot()["solver"])


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


def test_raw_colour_frames_downsample_at_least_twice() -> None:
    rows = 4176  # an ASI2600MC frame
    assert downsample_for(None, rows, bayer=True) == 2
    assert downsample_for(1.8, rows, bayer=True) == 2  # focused: rejected at -z 1
    assert downsample_for(5.0, rows, bayer=True) == 2
    assert downsample_for(22.0, 6388, bayer=True) == 3
    assert downsample_for(1.0, 1080, bayer=True) == 2


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
    store = StateStore()
    service = SolverService(store, fake_astap)
    with pytest.raises(SolveError, match="no star database for a 12° field") as error:
        service.check(12)
    assert error.value.reason is Failure.NO_DATABASE
    with pytest.raises(SolveError, match="no star database for a 12° field"):
        await service.solve(frame, fov=12, hint=None)
    assert solver_state(store)["failure"]["reason"] == "no_database"


async def test_without_astap(frame: Path) -> None:
    store = StateStore()
    service = SolverService(store, None)
    await service.start()
    assert solver_state(store)["available"] is False
    with pytest.raises(SolveError, match="not installed"):
        await service.solve(frame, fov=2.34, hint=None)
    assert solver_state(store)["failure"]["reason"] == "unavailable"


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (1, Failure.NO_SOLUTION),
        (2, Failure.NO_STARS),
        (16, Failure.UNREADABLE),
        (32, Failure.NO_DATABASE),
        (33, Failure.ERROR),
        (7, Failure.ERROR),
    ],
)
async def test_failures_say_why(
    fake_astap: Astap, frame: Path, monkeypatch: pytest.MonkeyPatch, code: int, reason: Failure
) -> None:
    store = StateStore()
    service = SolverService(store, fake_astap)
    await service.solve(frame, fov=2.34, hint=None)
    monkeypatch.setenv("FAKE_ASTAP_EXIT", str(code))
    with pytest.raises(SolveError) as error:
        await service.solve(frame, fov=2.34, hint=None)
    assert error.value.reason is reason
    state = solver_state(store)
    SolverState.model_validate(state)
    assert state["failure"]["reason"] == reason.value
    assert state["failure"]["message"] == str(error.value)
    assert state["last"] is not None  # the previous solution stays

    monkeypatch.delenv("FAKE_ASTAP_EXIT")
    await service.solve(frame, fov=2.34, hint=None)
    assert solver_state(store)["failure"] is None


async def test_too_few_stars(
    fake_astap: Astap, frame: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What ASTAP 2026.10.30 wrote for a frame of noise: the exit code of a failed search.
    (tmp_path / "result.ini").write_text("PLTSOLVD=F\nERROR=Not enough stars.\n")
    monkeypatch.setenv("FAKE_ASTAP_EXIT", "1")
    with pytest.raises(SolveError) as error:
        await SolverService(StateStore(), fake_astap).solve(frame, fov=2.34, hint=None)
    assert error.value.reason is Failure.NO_STARS
    assert str(error.value) == "Not enough stars."


async def test_annotations_go_to_the_latest_solution(fake_astap: Astap, frame: Path) -> None:
    store = StateStore()
    service = SolverService(store, fake_astap)
    first = await service.solve(frame, fov=2.34, hint=None)
    described = service.annotate(first, {"synced": True})
    assert described["synced"] is True
    assert solver_state(store)["last"]["synced"] is True
    SolverState.model_validate(solver_state(store))

    await service.solve(frame, fov=2.34, hint=None)
    # A newer solution replaced it: the state is left alone.
    assert service.annotate(first, {"synced": True})["synced"] is True
    assert solver_state(store)["last"]["synced"] is False


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
