"""Saved frames solved for the framing chart's background (phase 3.7c, ADR 0020).

A saved light's plate solution is kept with it in the frame catalog, with a JPEG of
the frame as NOCS shows it, downscaled (``<data>/sky/<id>.jpg``): the target page
lays the maintainer's own frames under the chart's stars, even while the drive
they are on is unplugged.

Frames get there two ways: "Solve this frame" on a saved light (``record``, from
``PointingService.solve_kept``), and ``start``, which solves a saved frame from the
catalog in a job of its own (the target page's "Solve one of my frames"). A frame
that fails to solve is recorded as such, so it is not offered again.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import anyio
import anyio.to_thread
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]

from nocs.imaging.pipeline import FrameAnalysis
from nocs.jobs import JobContext, JobManager
from nocs.mount.coords import jnow_to_j2000
from nocs.mount.service import PointingError
from nocs.solving import Hint, SolveError, SolveResult
from nocs.state import Json
from nocs.storage import FrameRow, FrameSolution, Located

log = logging.getLogger(__name__)

IMAGE_WIDTH = 1024
"""Pixels across a saved frame's JPEG: sharp on a phone's chart, 100 to 200 kB."""
NEAR = 20
"""Solved frames at most in one answer."""

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline


class Storage(Protocol):
    """The frame catalog (``StorageService``); blocking, called from threads."""

    def frame_file(self, frame_id: int) -> tuple[FrameRow, Path]: ...
    def set_solution(self, frame_id: int, solution: FrameSolution | str) -> None: ...
    def solved_near(
        self, ra: float, dec: float, radius: float, limit: int = 20
    ) -> list[tuple[Located, FrameSolution]]: ...
    def unsolved_lights(self, target: str) -> list[Located]: ...


class Renderer(Protocol):
    """The imaging worker (``ImageWorker``)."""

    async def render(
        self, fits_path: str, jpeg_path: str, bayer: str | None, width: int
    ) -> FrameAnalysis: ...


class Solver(Protocol):
    """``SolverService``."""

    def check(self, fov: float | None) -> object: ...
    async def solve(
        self,
        image: Path,
        *,
        fov: float | None,
        hint: Hint | None,
        hfr: float | None = None,
        blind: bool = True,
        publish: bool = True,
    ) -> SolveResult: ...


@dataclass(frozen=True, slots=True)
class SkyFrames:
    """What the chart can show around a point, and what could be solved for it."""

    solved: list[tuple[Located, FrameSolution, bool]]
    """Solved frames near the point, newest first, and whether each has its JPEG."""
    unsolved: int
    """Lights of the target never tried."""
    candidate: int | None
    """The one to solve next: most stars, on a drive that is plugged in."""


class SavedFrames:
    def __init__(
        self,
        jobs: JobManager,
        storage: Storage,
        worker: Renderer,
        solver: Solver,
        directory: Path,
    ) -> None:
        self._jobs = jobs
        self._storage = storage
        self._worker = worker
        self._solver = solver
        self._directory = directory

    def image(self, frame_id: int) -> Path | None:
        """A solved frame's JPEG, if there is one."""
        path = self._directory / f"{frame_id}.jpg"
        return path if path.is_file() else None

    def near(self, ra: float, dec: float, radius: float, target: str | None) -> SkyFrames:
        """Solved frames within ``radius`` degrees of a J2000 point, and the lights of
        ``target`` (a name in the catalog) still to solve. Blocking."""
        solved = [
            (located, solution, self.image(located.row.id) is not None)
            for located, solution in self._storage.solved_near(ra, dec, radius, NEAR)
        ]
        unsolved = self._storage.unsolved_lights(target) if target else []
        candidate = next((f.row.id for f in unsolved if f.path is not None), None)
        return SkyFrames(solved, len(unsolved), candidate)

    def start(self, frame_id: int) -> str:
        """Solve a saved frame in a job of its own, which locks nothing; returns its id."""
        self._solver.check(None)

        async def job(context: JobContext) -> Json:
            solution = await self.solve(context, frame_id)
            return {
                "id": frame_id,
                "ra": solution.ra,
                "dec": solution.dec,
                "rotation": solution.rotation,
                "scale": solution.scale,
                "mirrored": solution.mirrored,
            }

        return self._jobs.start("solve_saved", [], job)

    async def solve(self, context: JobContext, frame_id: int) -> FrameSolution:
        """Solve a saved light and keep its solution and JPEG; raises SolveError,
        PointingError, KeyError, FileNotFoundError or FrameUnavailableError."""
        row, path = await anyio.to_thread.run_sync(self._storage.frame_file, frame_id)
        if row.frame_type != "light":
            raise PointingError(f"frame {frame_id} is a {row.frame_type} frame, not a light")
        context.progress(None, "measuring the stars")
        analysis = await self._render(frame_id, path)
        hint, fov = await anyio.to_thread.run_sync(_header_hint, path)
        context.progress(None, "solving")
        try:
            result = await self._solver.solve(
                path, fov=fov, hint=hint, hfr=analysis.hfr, publish=False
            )
        except SolveError as error:
            await anyio.to_thread.run_sync(self._storage.set_solution, frame_id, str(error))
            raise
        return await self._keep(frame_id, result)

    async def record(self, frame_id: int, path: Path, result: SolveResult) -> None:
        """Keep the solution of a saved frame solved elsewhere ("Solve this frame");
        logs what fails, never raises."""
        try:
            await self._render(frame_id, path)
            await self._keep(frame_id, result)
        except Exception as e:
            log.warning("could not keep the solution of frame %d: %s", frame_id, e)

    async def _render(self, frame_id: int, path: Path) -> FrameAnalysis:
        jpeg = self._directory / f"{frame_id}.jpg"
        return await self._worker.render(str(path), str(jpeg), None, IMAGE_WIDTH)

    async def _keep(self, frame_id: int, result: SolveResult) -> FrameSolution:
        s = result.solution
        solution = FrameSolution(
            ra=s.ra,
            dec=s.dec,
            scale=s.scale,
            rotation=s.rotation,
            mirrored=s.mirrored,
            width=s.width,
            height=s.height,
            solved=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        await anyio.to_thread.run_sync(self._storage.set_solution, frame_id, solution)
        return solution


def _header_hint(path: Path) -> tuple[Hint | None, float | None]:
    """Where the mount said the frame pointed (J2000), and its height in degrees,
    from its header (blocking)."""
    header = _fits.getheader(path)
    hint: Hint | None = None
    ra, dec = header.get("RA"), header.get("DEC")
    if isinstance(ra, int | float) and isinstance(dec, int | float):
        hours, degrees = float(ra) / 15, float(dec)
        taken = header.get("DATE-OBS")
        if header.get("EQUINOX") != 2000 and isinstance(taken, str):
            try:
                when = datetime.fromisoformat(taken).replace(tzinfo=UTC)
            except ValueError:
                pass
            else:
                j2000 = jnow_to_j2000(hours, degrees, when)
                hours, degrees = j2000.ra, j2000.dec
        hint = Hint(hours % 24, max(-90.0, min(90.0, degrees)))
    fov: float | None = None
    focal, pixel, rows = header.get("FOCALLEN"), header.get("YPIXSZ"), header.get("NAXIS2")
    if not isinstance(pixel, int | float):
        pixel = header.get("XPIXSZ")
    if (
        isinstance(focal, int | float)
        and isinstance(pixel, int | float)
        and isinstance(rows, int)
        and focal > 0
        and pixel > 0
    ):
        # XPIXSZ and YPIXSZ are of binned pixels (FITS convention, INDI and ASIAIR).
        fov = math.degrees(rows * pixel / 1000 / focal)
    return hint, fov
