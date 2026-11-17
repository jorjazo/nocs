"""Find the Sun or the Moon and centre it by its brightness, without solving (ADR 0049).

``FinderService.start`` runs a ``find`` job with the main camera that locks what
centring locks. It:

1. tracks the body at its rate (lunar, solar) when the mount offers it;
2. searches: slews to the body's ephemeris position (or where the mount points, with
   ``here``) and along a square spiral around it, a frame at each point, until a
   frame shows the disc. Aims are offsets from the body's position at each slew, so
   its motion does not add up. Points below the horizon are skipped, and so are those
   near the Sun before its warning is acknowledged. A frame without the disc and
   brighter than half the scale is taken again at a quarter of the exposure;
3. calibrates: moves east, then north, and measures how the disc moved in the frame;
4. centres: moves so the disc's centre lands on the frame's, until within the
   tolerance;
5. syncs the mount to where it then points: the body's position, less what is left
   of the centring.

A run that fails or is cancelled puts the tracking rate it replaced back; one that
succeeds leaves the body's, until the next go to (``MountService.track_body``).

Every frame becomes the main camera's preview, so Explore follows the search.

State under ``("finder",)``: ``None`` until the first run, then that run as it goes::

    {job, body, state, phase, options, exposure, binning, searched, positions, skipped,
     frames,
     disc, offset, error, attempts, track_mode, synced, warning, failure, started,
     finished}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path as FsPath
from typing import Protocol

import anyio

from nocs.clock import Clock
from nocs.devices import Coordinates, DeviceError, FrameType, Location
from nocs.devices.camera import Range
from nocs.equipment import Role
from nocs.finder.search import Axes, Offset, aim, offset_between, spiral
from nocs.imaging import Disc, Shot
from nocs.jobs import JobContext, JobManager
from nocs.mount.coords import jnow_to_horizontal, jnow_to_j2000
from nocs.mount.service import Frame, PointingError, SunWarningError
from nocs.pointing import solve
from nocs.pointing.solve import PointingService, restore_binning
from nocs.sky.bodies import Body, BodyPosition, position
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("finder",)
CAMERA = Role.MAIN_CAMERA
EXPOSURE = 0.1
"""Seconds of the search's frames: the Sun behind its filter, the Moon by night and by
day all stand out, saturated or not."""
MIN_EXPOSURE = 1e-4
"""Seconds: the shortest frame, or the camera's own shortest if longer."""
BRIGHT = 0.5
"""A frame's median level, of the full scale, above which it is taken again shorter."""
SHORTER = 4.0
MAX_BINNING = 4
MAX_RADIUS = 30.0
"""Degrees: the widest search."""
MAX_ATTEMPTS = 10
MAX_POSITIONS = 2000
"""Frames of the widest search: a few hours at most."""
SEARCH_STEP = 0.7
"""Of the field's short side: the search's points overlap a little."""
PROBE = 0.25
"""Of the field's short side: each move that measures the camera's axes."""
FITS = 0.9
"""Of the field's short side: the largest disc the finder centres by its limb."""
TRACK_MODES = {Body.SUN: "solar", Body.MOON: "lunar"}
NAMES = {Body.SUN: "Sun", Body.MOON: "Moon"}


class FinderError(Exception):
    """The finder cannot run, or did not find or centre the body."""


class RunState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Phase(StrEnum):
    TRACKING = "tracking"
    SEARCHING = "searching"
    CALIBRATING = "calibrating"
    CENTRING = "centring"
    SYNCING = "syncing"


@dataclass(frozen=True, slots=True)
class FinderOptions:
    body: Body
    radius: float = 5.0
    """Degrees around the body (or where the mount points) to search."""
    exposure: float = EXPOSURE
    binning: int | None = None
    """For the frames only; the camera's largest up to 4 when ``None``."""
    tolerance: float = 2.0
    """Arcminutes from the frame's centre."""
    attempts: int = 6
    """Moves to centre the disc, at most."""
    settle: float = 1.0
    """Seconds after each slew."""
    here: bool = False
    """Search around where the mount points, not the body's position."""
    sync: bool = True
    track: bool = True
    """Track at the body's rate."""

    def check(self) -> None:
        if not 0 <= self.radius <= MAX_RADIUS:
            raise ValueError(f"the search radius must be 0..{MAX_RADIUS:g}°")
        if not MIN_EXPOSURE <= self.exposure <= 10:
            raise ValueError(f"the exposure must be {MIN_EXPOSURE:g}..10 s")
        if self.binning is not None and self.binning < 1:
            raise ValueError("the binning must be at least 1")
        if not 0 < self.tolerance <= 60:
            raise ValueError("the tolerance must be 0..60 arcminutes")
        if not 1 <= self.attempts <= MAX_ATTEMPTS:
            raise ValueError(f"the attempts must be 1..{MAX_ATTEMPTS}")
        if not 0 <= self.settle <= 60:
            raise ValueError("the settling time must be 0..60 s")


class CameraDevice(solve.CameraDevice, Protocol):
    @property
    def exposure_range(self) -> Range | None: ...


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
    async def disc(self, shot: Shot, radius: float) -> Disc: ...
    async def show(self, role: Role, shot: Shot) -> None: ...


class Mounts(Protocol):
    """The mount role (``MountService``)."""

    def site(self) -> Location | None: ...
    def position_jnow(self) -> Coordinates: ...
    def track_modes(self) -> list[str]: ...
    def check_goto(
        self, ra: float, dec: float, *, force: bool = False, frame: Frame = "j2000"
    ) -> None: ...
    async def slew(
        self,
        context: JobContext,
        ra: float,
        dec: float,
        *,
        force: bool = False,
        frame: Frame = "j2000",
        body_rate: bool = False,
    ) -> Coordinates: ...
    async def settle(self, seconds: float) -> None: ...
    async def track_body(self, mode: str | None, *, job: str) -> None: ...
    async def restore_rate(self, *, job: str) -> None: ...
    async def sync(
        self,
        ra: float,
        dec: float,
        when: datetime | None = None,
        *,
        job: str | None = None,
        check: bool = True,
    ) -> Coordinates: ...


@dataclass(slots=True)
class _Run:
    job: str
    options: FinderOptions
    exposure: float
    binning: int | None = None
    started: str = field(default_factory=lambda: _now())
    state: RunState = RunState.RUNNING
    phase: Phase = Phase.TRACKING
    searched: int = 0
    positions: int = 0
    skipped: int = 0
    """Search points near the Sun, skipped before its warning is acknowledged."""
    frames: int = 0
    disc: Disc | None = None
    offset: Offset | None = None
    error: float | None = None
    attempts: int = 0
    track_mode: str | None = None
    synced: bool = False
    warning: str | None = None
    failure: str | None = None
    finished: str | None = None

    def summary(self) -> dict[str, Json]:
        options = self.options
        disc = self.disc
        return {
            "job": self.job,
            "body": options.body.value,
            "state": self.state.value,
            "phase": self.phase.value,
            "options": {
                "radius": options.radius,
                "exposure": options.exposure,
                "binning": options.binning,
                "tolerance": options.tolerance,
                "here": options.here,
                "sync": options.sync,
                "track": options.track,
            },
            "exposure": self.exposure,
            "binning": self.binning,
            "searched": self.searched,
            "positions": self.positions,
            "skipped": self.skipped,
            "frames": self.frames,
            "disc": (
                {
                    "found": disc.found,
                    "x": disc.x,
                    "y": disc.y,
                    "radius": disc.radius,
                    "width": disc.width,
                    "height": disc.height,
                    "background": disc.background,
                }
                if disc is not None
                else None
            ),
            "offset": (
                {"east": round(self.offset.east, 2), "north": round(self.offset.north, 2)}
                if self.offset is not None
                else None
            ),
            "error": round(self.error, 2) if self.error is not None else None,
            "attempts": self.attempts,
            "track_mode": self.track_mode,
            "synced": self.synced,
            "warning": self.warning,
            "failure": self.failure,
            "started": self.started,
            "finished": self.finished,
        }


class FinderService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        frames: Frames,
        mount: Mounts,
        clock: Clock,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._frames = frames
        self._mount = mount
        self._clock = clock
        self._run: _Run | None = None
        store.set(ROOT, None)

    @staticmethod
    def resources() -> list[str]:
        """What a run locks: the main camera (with its filter wheel and focuser) and the
        mount, as centring does."""
        return PointingService.resources(CAMERA)

    def check(self, options: FinderOptions) -> BodyPosition:
        """Raise what ``start`` would raise now, but for a busy mount (guiding, which the
        caller stops first); returns where the body is."""
        options.check()
        camera = self._frames.camera(CAMERA)
        if options.binning is not None and options.binning > camera.max_binning:
            raise ValueError(f"binning must be 1..{camera.max_binning}")
        field = self._field()
        site = self._site()
        body = position(options.body, site, self._clock.now())
        _check_body(body, field)
        positions = len(spiral(options.radius * 60, SEARCH_STEP * min(field) * 60))
        if positions > MAX_POSITIONS:
            raise ValueError(
                f"a {options.radius:g}° search takes {positions} frames with this field, "
                f"more than {MAX_POSITIONS}: narrow it"
            )
        self._mount.check_goto(body.jnow.ra, body.jnow.dec, frame="jnow")
        self._jobs.check_free(r for r in self.resources() if r != Role.MOUNT.value)
        return body

    def start(self, options: FinderOptions) -> str:
        """Find and centre ``options.body`` in a job of its own; returns the job id."""
        self.check(options)
        resources = self.resources()
        self._jobs.check_free(resources)

        async def job(context: JobContext) -> Json:
            return await self.find(context, options)

        return self._jobs.start("find", resources, job)

    async def find(self, context: JobContext, options: FinderOptions) -> dict[str, Json]:
        """Find and centre the body inside ``context``'s job, which must hold the main
        camera and the mount; returns the run's summary. Raises FinderError."""
        options.check()
        run = _Run(context.id, options, options.exposure)
        self._run = run
        self._publish()
        try:
            await self._find(context, run)
        except BaseException as e:
            cancelled = isinstance(e, anyio.get_cancelled_exc_class())
            run.state = RunState.CANCELLED if cancelled else RunState.FAILED
            if not cancelled:
                run.failure = str(e) or type(e).__name__
            raise
        else:
            run.state = RunState.SUCCEEDED
        finally:
            run.finished = _now()
            self._publish()
        return run.summary()

    # -- internals ----------------------------------------------------------

    async def _find(self, context: JobContext, run: _Run) -> None:
        options = run.options
        field = self._field()
        site = self._site()
        body = position(options.body, site, self._clock.now())
        _check_body(body, field)
        camera = self._frames.camera(CAMERA)
        before = camera.binning[0]
        run.binning = options.binning or min(MAX_BINNING, camera.max_binning)
        exposures = camera.exposure_range
        shortest = max(MIN_EXPOSURE, exposures.min if exposures is not None else 0.0)
        run.exposure = max(run.exposure, shortest)
        if run.binning != before:
            await camera.set_binning(run.binning)
        try:
            await self._steps(context, run, field, site, body.semidiameter / field[0], shortest)
        except BaseException:
            with anyio.CancelScope(shield=True):
                try:
                    await self._mount.restore_rate(job=context.id)
                except Exception as e:  # the run's own failure, or cancellation, goes on
                    log.error("finder: could not put the tracking rate back: %s", e)
            raise
        finally:
            if run.binning != before:
                await restore_binning(camera, before)

    async def _steps(
        self,
        context: JobContext,
        run: _Run,
        field: tuple[float, float],
        site: Location,
        radius: float,
        shortest: float,
    ) -> None:
        options = run.options
        name = NAMES[options.body]
        short = min(field) * 60

        if options.track:
            run.phase = Phase.TRACKING
            self._report(context, run, f"tracking the {name}")
            wanted = TRACK_MODES[options.body]
            mode = wanted if wanted in self._mount.track_modes() else None
            await self._mount.track_body(mode, job=context.id)
            run.track_mode = mode
            if mode is None:
                run.warning = f"the mount has no {wanted} tracking: it tracks at its own rate"

        centre = Offset(0.0, 0.0)
        if options.here:
            body = position(options.body, site, self._clock.now())
            centre = offset_between(body.jnow, self._mount.position_jnow())

        run.phase = Phase.SEARCHING
        points = spiral(options.radius * 60, SEARCH_STEP * short)
        run.positions = len(points)
        found: tuple[Offset, Disc] | None = None
        for number, point in enumerate(points, start=1):
            run.searched = number
            where = centre + point
            try:
                disc = await self._look(
                    context,
                    run,
                    site,
                    where,
                    radius,
                    shortest,
                    f"looking {number} of {len(points)}",
                )
            except SunWarningError:
                run.skipped += 1
                continue
            if disc is not None and disc.found:
                found = (where, disc)
                break
        if found is None:
            skipped = (
                f"; {run.skipped} places near the Sun were not looked at, before its "
                "warning is acknowledged"
                if run.skipped
                else ""
            )
            raise FinderError(
                f"the {name} is not within {options.radius:g}° of where the finder looked: "
                f"bring it closer with the pad and search from there{skipped}"
            )
        where, disc = found
        log.info("finder: the %s is %.1f' from its position", name, where.size)

        run.phase = Phase.CALIBRATING
        probe = PROBE * short
        east, where, disc = await self._probe(
            context, run, site, where, disc, Offset(probe, 0), radius, shortest
        )
        north, where, disc = await self._probe(
            context, run, site, where, disc, Offset(0, probe), radius, shortest
        )
        axes = Axes(east, north)
        problem = axes.problem(disc.width / (field[0] * 60))
        if problem is not None:
            raise FinderError(f"{problem}: is the mount moving and the camera still?")

        run.phase = Phase.CENTRING
        move = Offset(0.0, 0.0)
        for attempt in range(options.attempts + 1):
            assert disc.x is not None
            assert disc.y is not None
            move = axes.move((disc.width - 1) / 2 - disc.x, (disc.height - 1) / 2 - disc.y)
            run.error = move.size
            self._publish()
            if move.size <= options.tolerance:
                break
            if attempt == options.attempts:
                raise FinderError(
                    f"the {name} is still {move.size:.1f}' from the centre after "
                    f"{options.attempts} moves"
                )
            run.attempts = attempt + 1
            where = where + move
            seen = await self._look(
                context, run, site, where, radius, shortest, f"centring, move {attempt + 1}"
            )
            if seen is None or not seen.found:
                raise FinderError(f"the {name} left the frame while centring it")
            disc = seen
        run.offset = where
        log.info("finder: %s centred, %.1f' off", name, run.error or 0.0)

        if options.sync:
            run.phase = Phase.SYNCING
            self._report(context, run, "syncing the mount")
            now = self._clock.now()
            body = position(options.body, site, now)
            # The mount points ``move`` short of the body: one more move would centre it.
            there = aim(body.jnow, move * -1.0)
            j2000 = jnow_to_j2000(there.ra, there.dec, now)
            try:
                await self._mount.sync(j2000.ra, j2000.dec, now, job=context.id)
            except (PointingError, DeviceError) as e:
                log.warning("finder: no sync: %s", e)
                run.warning = f"the mount was not synced: {e}"
            else:
                run.synced = True

    async def _look(
        self,
        context: JobContext,
        run: _Run,
        site: Location,
        where: Offset,
        radius: float,
        shortest: float,
        message: str,
    ) -> Disc | None:
        """Slew to ``where`` from the body and take a frame; ``None`` below the horizon.
        Raises SunWarningError near the Sun before its warning is acknowledged."""
        now = self._clock.now()
        body = position(run.options.body, site, now)
        target = aim(body.jnow, where)
        if jnow_to_horizontal(target.ra, target.dec, site, now).alt < 0:
            return None
        run.offset = where
        self._report(context, run, message)
        await self._mount.slew(context, target.ra, target.dec, frame="jnow", body_rate=True)
        await self._mount.settle(run.options.settle)
        while True:
            shot = await self._frames.take(
                context, CAMERA, run.exposure, FrameType.LIGHT, f"{message}: "
            )
            try:
                disc = await self._frames.disc(shot, radius)
            except BaseException:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(_delete, shot.path)
                raise
            await self._frames.show(CAMERA, shot)
            run.frames += 1
            run.disc = disc
            self._publish()
            if disc.found or disc.background <= BRIGHT or run.exposure <= shortest:
                return disc
            run.exposure = max(shortest, run.exposure / SHORTER)
            log.info("finder: a bright frame; %g s now", run.exposure)

    async def _probe(
        self,
        context: JobContext,
        run: _Run,
        site: Location,
        start: Offset,
        seen: Disc,
        step: Offset,
        radius: float,
        shortest: float,
    ) -> tuple[tuple[float, float], Offset, Disc]:
        """Move ``step`` from ``start``, where the frame showed ``seen`` (or the other
        way, if the disc leaves the frame): pixels the disc moved per arcminute, where
        the mount went and what it saw there."""
        assert seen.x is not None
        assert seen.y is not None
        for sign in (1.0, -1.0):
            where = start + step * sign
            disc = await self._look(
                context, run, site, where, radius, shortest, "measuring the axes"
            )
            if disc is not None and disc.found:
                assert disc.x is not None
                assert disc.y is not None
                moved = sign * step.size
                return ((disc.x - seen.x) / moved, (disc.y - seen.y) / moved), where, disc
        raise FinderError("the disc left the frame while the finder measured the camera's axes")

    def _field(self) -> tuple[float, float]:
        """The main camera's field, degrees wide and high, which binning does not change."""
        value = self._store.get(("cameras", CAMERA.value, "field"))
        if isinstance(value, dict):
            width, height = value.get("width"), value.get("height")
            if (
                isinstance(width, int | float)
                and isinstance(height, int | float)
                and width > 0
                and height > 0
            ):
                return float(width), float(height)
        raise FinderError(
            "the main camera's field is unknown: give the telescope's focal length in the profile"
        )

    def _site(self) -> Location:
        site = self._mount.site()
        if site is None:
            raise FinderError("the site is unknown: choose the site")
        return site

    def _report(self, context: JobContext, run: _Run, message: str) -> None:
        fraction = None
        if run.phase is Phase.SEARCHING and run.positions:
            fraction = (run.searched - 1) / run.positions
        context.progress(fraction, message)
        self._publish()

    def _publish(self) -> None:
        if self._run is not None:
            self._store.set(ROOT, self._run.summary())


def _check_body(body: BodyPosition, field: tuple[float, float]) -> None:
    name = NAMES[body.body]
    if body.alt <= 0:
        raise FinderError(f"the {name} is below the horizon")
    size = 2 * body.semidiameter
    if size > FITS * min(field):
        raise FinderError(
            f"the {name}'s disc ({size:.2f}°) does not fit the main camera's field "
            f"({field[0]:.2f}° by {field[1]:.2f}°): the finder needs a wider field"
        )


def _delete(path: FsPath) -> None:
    path.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
