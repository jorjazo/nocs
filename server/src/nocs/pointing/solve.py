"""Solve and sync: take a frame, solve it, and tell the mount where it points.

``PointingService.solve_frame`` works inside any job that holds the camera (and the
mount, to keep it still), so centring, polar alignment and re-centring call it from
their own; ``start`` runs it in a ``solve`` job of its own for the API. A solve:

1. reads where the mount says it points (J2000), the hint and the reference for
   the offset;
2. takes a frame (a light, never saved nor previewed) and measures its stars in
   the imaging worker, whose HFR chooses ASTAP's downsampling (ADR 0018);
3. solves it near the hint, then over the whole sky;
4. with ``sync``, syncs the mount to the solution, converted to JNow at the
   frame's mid-exposure (ADR 0015).

The frame is deleted afterwards. The solution, with the mount's position, the
offset between the two and whether the mount was synced, goes to ``solver.last``;
``sync`` syncs the mount to it later, if the mount has not moved since.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path as FsPath
from typing import Protocol

import anyio

from nocs.devices import Coordinates, DeviceError, FrameType
from nocs.equipment import Role
from nocs.imaging import Shot, StarMetrics
from nocs.jobs import JobContext, JobManager
from nocs.mount.service import MountNotReadyError, PointingError
from nocs.solving import Hint, SolveResult, separation
from nocs.state import Json, StateStore

log = logging.getLogger(__name__)

MOVED = 1.0
"""Arcminutes the mount may have moved since a frame for a later sync to its solution."""
MAX_EXPOSURE = 600.0


class CameraDevice(Protocol):
    """What a solve needs of a camera (``nocs.devices.Camera``)."""

    @property
    def binning(self) -> tuple[int, int]: ...
    @property
    def max_binning(self) -> int: ...
    async def set_binning(self, x: int, y: int | None = None) -> None: ...


class Frames(Protocol):
    """Frames inside a job (``CaptureService``)."""

    def camera(self, role: Role) -> CameraDevice: ...
    async def take(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        label: str = "",
    ) -> Shot: ...
    async def measure(self, shot: Shot, *, discard: bool = True) -> StarMetrics: ...


class Solver(Protocol):
    """``SolverService``."""

    def check(self, fov: float | None) -> object: ...
    async def solve(
        self,
        image: FsPath,
        *,
        fov: float | None,
        hint: Hint | None,
        hfr: float | None = None,
        blind: bool = True,
    ) -> SolveResult: ...
    def annotate(self, result: SolveResult, fields: dict[str, Json]) -> dict[str, Json]: ...


class Mounts(Protocol):
    """The mount role (``MountService``)."""

    def position(self) -> Coordinates: ...
    async def sync(
        self, ra: float, dec: float, when: datetime | None = None, *, job: str | None = None
    ) -> Coordinates: ...


@dataclass(frozen=True, slots=True)
class SolveOptions:
    exposure: float | None = None
    """Seconds; the camera's current exposure when ``None``."""
    binning: int | None = None
    """For this frame only; the camera's current binning when ``None``."""
    sync: bool = False
    blind: bool = True
    """Search the whole sky when the frame is not where the mount says."""

    def check(self) -> None:
        if self.exposure is not None and not 0 < self.exposure <= MAX_EXPOSURE:
            raise ValueError(f"the exposure must be 0..{MAX_EXPOSURE:g} s")
        if self.binning is not None and self.binning < 1:
            raise ValueError("the binning must be at least 1")


@dataclass(frozen=True, slots=True)
class Offset:
    """Where a frame is from where the mount thought it pointed, arcminutes."""

    angle: float
    """On the sky."""
    ra: float
    """Along the RA axis on the sky (scaled by cos Dec), east positive."""
    dec: float
    """North positive."""


def offset(ra: float, dec: float, to_ra: float, to_dec: float) -> Offset:
    """From (``ra``, ``dec``) to (``to_ra``, ``to_dec``): RA in hours, Dec in degrees."""
    hours = (to_ra - ra + 12) % 24 - 12
    return Offset(
        angle=separation(ra, dec, to_ra, to_dec) * 60,
        ra=hours * 15 * 60 * math.cos(math.radians(dec)),
        dec=(to_dec - dec) * 60,
    )


@dataclass(frozen=True, slots=True)
class FrameSolve:
    result: SolveResult
    taken: datetime
    """Mid-exposure."""
    mount: Coordinates | None
    """Where the mount said it pointed (J2000) as the frame started; ``None`` without one."""
    offset: Offset | None
    """From ``mount`` to the solution."""
    stars: int
    hfr: float | None
    synced: bool = False


class PointingService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        capture: Frames,
        solver: Solver,
        mount: Mounts,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._capture = capture
        self._solver = solver
        self._mount = mount
        self._last: FrameSolve | None = None

    def start(self, options: SolveOptions, role: Role = Role.MAIN_CAMERA) -> str:
        """Solve (and sync) in a job of its own (locking ``resources``); returns the job id."""
        self.check(options, role)

        async def job(context: JobContext) -> Json:
            solved = await self.solve_frame(context, options, role)
            return self._describe(solved)

        return self._jobs.start("solve", self.resources(role), job)

    def check(self, options: SolveOptions, role: Role = Role.MAIN_CAMERA) -> None:
        """Raise now what a solve with ``options`` would fail on in its job: no
        camera, a binning it lacks, no solver for its field, no mount for a sync."""
        options.check()
        camera = self._capture.camera(role)
        if options.binning is not None and options.binning > camera.max_binning:
            raise ValueError(f"binning must be 1..{camera.max_binning}")
        self._solver.check(self._fov(role))
        if options.sync:
            self._mount.position()  # MountNotReadyError without a mount

    @staticmethod
    def resources(role: Role = Role.MAIN_CAMERA) -> list[str]:
        """What a job that solves frames of ``role`` locks: what an exposure of the
        camera locks, and the mount, which must not move during the frame."""
        resources = [role.value, Role.MOUNT.value]
        if role is Role.MAIN_CAMERA:
            resources += [Role.FILTER_WHEEL.value, Role.FOCUSER.value]
        return resources

    async def solve_frame(
        self, context: JobContext, options: SolveOptions, role: Role = Role.MAIN_CAMERA
    ) -> FrameSolve:
        """Take a frame with ``role`` inside ``context``'s job, solve it and, with
        ``options.sync``, sync the mount to it; raises SolveError.

        The job must hold the camera, and the mount for a sync.
        """
        options.check()
        mount = self._mount_position()
        if options.sync and mount is None:
            raise MountNotReadyError("the mount is not connected")
        exposure = options.exposure or self._exposure(role)
        fov = self._fov(role)
        hint = Hint(mount.ra, mount.dec) if mount is not None else None

        camera = self._capture.camera(role)
        binning = camera.binning[0]
        rebin = options.binning is not None and options.binning != binning
        if rebin:
            assert options.binning is not None
            await camera.set_binning(options.binning)
        try:
            shot = await self._capture.take(context, role, exposure, FrameType.LIGHT)
        finally:
            if rebin:
                await _restore_binning(camera, binning)
        try:
            context.progress(None, "measuring the stars")
            stars = await self._capture.measure(shot, discard=False)
            context.progress(None, "solving")
            result = await self._solver.solve(
                shot.path, fov=fov, hint=hint, hfr=stars.hfr, blind=options.blind
            )
        finally:
            await anyio.to_thread.run_sync(lambda: shot.path.unlink(missing_ok=True))

        solution = result.solution
        solved = FrameSolve(
            result,
            taken=shot.taken - timedelta(seconds=shot.exposure / 2),
            mount=mount,
            offset=offset(mount.ra, mount.dec, solution.ra, solution.dec) if mount else None,
            stars=stars.stars,
            hfr=stars.hfr,
        )
        self._last = solved
        self._describe(solved)
        if options.sync:
            context.progress(None, "syncing the mount")
            solved = await self._sync(solved, job=context.id)
        return solved

    async def sync(self) -> dict[str, Json]:
        """Sync the mount to the last solution, if it still points where it did then."""
        solved = self._last
        if solved is None:
            raise PointingError("no frame has been solved yet")
        if solved.synced:
            raise PointingError("the mount was already synced to this solution")
        if solved.mount is None:
            raise PointingError("the mount was not connected when the frame was taken")
        now = self._mount.position()
        moved = separation(now.ra, now.dec, solved.mount.ra, solved.mount.dec) * 60
        if moved > MOVED:
            raise PointingError(
                f"the mount moved {moved:.1f} arcminutes since the frame: solve again"
            )
        return self._describe(await self._sync(solved))

    # -- internals ----------------------------------------------------------

    async def _sync(self, solved: FrameSolve, job: str | None = None) -> FrameSolve:
        solution = solved.result.solution
        await self._mount.sync(solution.ra, solution.dec, solved.taken, job=job)
        synced = FrameSolve(
            solved.result,
            solved.taken,
            solved.mount,
            solved.offset,
            solved.stars,
            solved.hfr,
            synced=True,
        )
        if self._last is solved:
            self._last = synced
        self._describe(synced)
        return synced

    def _describe(self, solved: FrameSolve) -> dict[str, Json]:
        """The solution's summary for the state (``solver.last``) and the job's result."""
        mount = solved.mount
        off = solved.offset
        return self._solver.annotate(
            solved.result,
            {
                "taken": solved.taken.isoformat(timespec="seconds"),
                "mount": {"ra": mount.ra, "dec": mount.dec} if mount else None,
                "offset": {"angle": off.angle, "ra": off.ra, "dec": off.dec} if off else None,
                "synced": solved.synced,
            },
        )

    def _mount_position(self) -> Coordinates | None:
        try:
            return self._mount.position()
        except (MountNotReadyError, DeviceError, KeyError) as e:
            log.debug("solving without the mount's position: %s", e)
            return None

    def _exposure(self, role: Role) -> float:
        value = self._store.get(("cameras", role.value, "exposure"))
        return float(value) if isinstance(value, int | float) else 2.0

    def _fov(self, role: Role) -> float | None:
        """The frame's height in degrees, which binning does not change."""
        value = self._store.get(("cameras", role.value, "field", "height"))
        return float(value) if isinstance(value, int | float) else None


async def _restore_binning(camera: CameraDevice, binning: int) -> None:
    try:
        with anyio.CancelScope(shield=True):
            await camera.set_binning(binning)
    except (DeviceError, ConnectionError) as e:
        log.error("could not restore the binning to %d: %s", binning, e)
