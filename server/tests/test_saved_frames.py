"""Saved frames solved for the framing chart (phase 3.7c): a fake ASTAP, a real catalog."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import anyio
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from fakeastap import calls, install_fake_astap

from nocs.api.schemas import JobInfo, SolverState
from nocs.imaging.pipeline import FrameAnalysis, Histogram
from nocs.jobs import JobManager
from nocs.pointing import SavedFrames
from nocs.solving import SolverService, separation
from nocs.state import StateStore
from nocs.storage import FrameRow, FrameSolution, Located
from nocs.storage.catalog import Catalog, NewFrame

_fits: Any = fits

pytestmark = pytest.mark.filterwarnings("ignore:File may have been truncated")

# The fake ASTAP answers with the solution of a frame of M 8.
M8_RA, M8_DEC = 270.92750 / 15, -23.76287

FRAME = NewFrame(
    night=datetime(2026, 7, 20).date(),
    site="Lab",
    target="M 8",
    volume="1234-ABCD",
    volume_label="SSD",
    mount_point="/media/nocs/SSD",
    directory=PurePosixPath(""),
    path=PurePosixPath("2026-07-20/Light/M_8/a.fits"),
    size=1000,
    started=datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
    exposure=120,
    frame_type="light",
    filter=None,
    profile="lab",
    camera="ZWO CCD ASI2600MC Pro",
    gain=100,
    offset=10,
    binning=1,
    temperature=-10,
    width=6248,
    height=4176,
)


class FakeStorage:
    """The catalog, with frames as files in a directory; ``unplugged`` ones have none."""

    def __init__(self, directory: Path) -> None:
        self.catalog = Catalog(directory / "catalog.sqlite")
        self.files: dict[int, Path] = {}
        self.unplugged: set[int] = set()

    def add(self, path: Path, frame: NewFrame = FRAME, stars: int | None = None) -> int:
        frame_id = self.catalog.add_frame(replace(frame, path=PurePosixPath(path.name)))
        self.catalog.set_metrics(frame_id, stars, None)
        self.files[frame_id] = path
        return frame_id

    def _located(self, row: FrameRow) -> Located:
        return Located(row, None if row.id in self.unplugged else self.files[row.id])

    def frame_file(self, frame_id: int) -> tuple[FrameRow, Path]:
        row = self.catalog.frame(frame_id)
        if row is None:
            raise KeyError(frame_id)
        return row, self.files[frame_id]

    def set_solution(self, frame_id: int, solution: FrameSolution | str) -> None:
        self.catalog.set_solution(frame_id, solution)

    def solved_near(
        self, ra: float, dec: float, radius: float, limit: int = 20
    ) -> list[tuple[Located, FrameSolution]]:
        found = self.catalog.solved_near(ra, dec, radius, limit)
        return [(self._located(row), solution) for row, solution in found]

    def unsolved_lights(self, target: str) -> list[Located]:
        return [self._located(row) for row in self.catalog.unsolved_lights(target)]


class FakeRenderer:
    """Writes a stand-in JPEG and says the stars' HFR, as the imaging worker would."""

    def __init__(self) -> None:
        self.rendered: list[tuple[str, str, int]] = []

    async def render(
        self, fits_path: str, jpeg_path: str, bayer: str | None, width: int
    ) -> FrameAnalysis:
        jpeg = anyio.Path(jpeg_path)
        await jpeg.parent.mkdir(parents=True, exist_ok=True)
        await jpeg.write_bytes(b"\xff\xd8 not really a JPEG")
        self.rendered.append((fits_path, jpeg_path, width))
        histogram = Histogram([0], 0, 1, 0, 0)
        return FrameAnalysis(jpeg_path, width, 683, True, 812, 3.2, histogram, 0.1)


def write_light(path: Path, **cards: object) -> Path:
    """The header of a frame of M 8's size, as INDI writes it (the fake reads no pixels)."""
    header = _fits.Header()
    for key, value in (("SIMPLE", True), ("BITPIX", 16), ("NAXIS", 2)):
        header[key] = value
    header["NAXIS1"] = 6248
    header["NAXIS2"] = 4176
    for key, value in cards.items():
        header[key.replace("_", "-")] = value
    header.tofile(path)
    return path


class Rig:
    def __init__(self, directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.directory = directory
        self.store = StateStore()
        self.jobs = JobManager(self.store)
        self.storage = FakeStorage(directory)
        self.renderer = FakeRenderer()
        self.solver = SolverService(self.store, install_fake_astap(directory, monkeypatch))
        self.sky = directory / "sky"
        self.saved = SavedFrames(self.jobs, self.storage, self.renderer, self.solver, self.sky)

    async def solve(self, frame_id: int) -> dict[str, Any]:
        job_id = self.saved.start(frame_id)
        await self.jobs.wait(job_id)
        job = self.store.get(("jobs", job_id))
        assert isinstance(job, dict)
        JobInfo.model_validate(job)
        return job

    def solver_state(self) -> dict[str, Any]:
        state = self.store.get(("solver",))
        assert isinstance(state, dict)
        SolverState.model_validate(state)
        return state


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    return Rig(tmp_path, monkeypatch)


async def test_a_saved_light_is_solved_and_kept_with_its_image(rig: Rig) -> None:
    # Where the mount said it pointed, in degrees (J2000), and the optics.
    path = write_light(
        rig.directory / "m8.fits", RA=271.0, DEC=-23.7, EQUINOX=2000, FOCALLEN=384.0, XPIXSZ=3.76
    )
    frame_id = rig.storage.add(path)
    job = await rig.solve(frame_id)
    assert job["state"] == "succeeded", job["error"]
    assert job["kind"] == "solve_saved"
    assert job["resources"] == []  # nothing moves, the camera is free
    assert job["result"]["id"] == frame_id

    [command] = calls(rig.directory)
    assert command[command.index("-f") + 1] == str(path)  # read where it was saved
    assert command[command.index("-ra") + 1] == f"{271.0 / 15:.6f}"
    assert command[command.index("-fov") + 1] == f"{4176 * 3.76 / 384 * 0.0572958:.4f}"
    assert command[command.index("-z") + 1] == "2"  # from the rendered frame's HFR (3.2 px)
    assert rig.renderer.rendered == [(str(path), str(rig.sky / f"{frame_id}.jpg"), 1024)]
    assert rig.saved.image(frame_id) == rig.sky / f"{frame_id}.jpg"

    found = rig.saved.near(M8_RA, M8_DEC, 2.0, "m 8")
    [(located, solution, has_image)] = found.solved
    assert located.row.id == frame_id
    assert has_image
    assert separation(solution.ra, solution.dec, M8_RA, M8_DEC) < 1 / 60
    assert solution.rotation == pytest.approx(360 - 316, abs=1)
    assert (found.unsolved, found.candidate) == (0, None)
    # An old frame says nothing about where the rig points now.
    assert rig.solver_state()["last"] is None


async def test_jnow_positions_are_moved_to_j2000(rig: Rig) -> None:
    path = write_light(
        rig.directory / "m8.fits", RA=271.3, DEC=-23.76, DATE_OBS="2026-07-21T01:00:00"
    )
    await rig.solve(rig.storage.add(path))
    [command] = calls(rig.directory)
    hint = float(command[command.index("-ra") + 1])
    # Precession at 18 h -24° moves RA by ~3.7 s a year: ~98 s since J2000.
    assert (271.3 / 15 - hint) * 3600 == pytest.approx(98, abs=4)
    assert command[command.index("-fov") + 1] == "0"  # no optics in the header


async def test_a_frame_that_does_not_solve_is_not_offered_again(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ASTAP_EXIT", "1")
    worse = rig.storage.add(write_light(rig.directory / "b.fits"), stars=40)
    best = rig.storage.add(write_light(rig.directory / "a.fits"), stars=900)
    assert (rig.saved.near(M8_RA, M8_DEC, 2.0, "M 8").candidate) == best
    job = await rig.solve(best)
    assert job["state"] == "failed"
    found = rig.saved.near(M8_RA, M8_DEC, 2.0, "M 8")
    assert (found.solved, found.unsolved, found.candidate) == ([], 1, worse)
    assert rig.solver_state()["failure"] is None
    # A frame on a drive that is not plugged in cannot be solved now.
    rig.storage.unplugged.add(worse)
    assert rig.saved.near(M8_RA, M8_DEC, 2.0, "M 8").candidate is None


async def test_only_lights(rig: Rig) -> None:
    flat = replace(FRAME, frame_type="flat", target=None)
    job = await rig.solve(rig.storage.add(write_light(rig.directory / "f.fits"), flat))
    assert job["state"] == "failed"
    assert "not a light" in str(job["error"])
    assert calls(rig.directory) == []
