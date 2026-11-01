"""The polar alignment job: three solved frames, then the knobs, frame by frame (ADR 0034).

``PolarAlignmentService.start`` runs a ``polar_align`` job holding what a solve holds
(the main camera, its filter wheel and focuser, and the mount), so it is refused while
guiding or any other job moves the mount. It:

1. checks the start where the mount points: away from the pole, every point above the
   horizon profile and the minimum altitude, and a last point that reads the knobs;
2. switches tracking on, solves a frame; turns the RA axis by ``step`` degrees away
   from the meridian (a go to at the mount's own Dec), solves; again; fits the axis;
3. exposes and solves at the last point again and again while the user turns the
   knobs: each frame, compared with the previous one, tells how far they were turned,
   and the axis and its error move by as much;
4. on ``finish``, goes back to the start (unless asked not to) and succeeds. A
   cancelled job stops where it is.

The mount is never synced. A frame that does not solve is taken again (up to
``RETRIES`` times for each of the three points; in step 3 it is noted and the next one
taken); no ASTAP or no star database ends the run at once.

State under ``("polar_alignment",)``: ``None`` until the first run, then that run as it
goes (the most recent one, finished or not)::

    {job, state, phase, options, points, rotation, axis, aligned, updates, warning,
     error, started, finished}
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

import anyio
import numpy as np

from nocs.align.polar import (
    SIDEREAL_RATE,
    Knobs,
    PolarError,
    Vector,
    altaz,
    angles,
    direction,
    fit_axis,
    knobs,
    polar_error,
    pole,
    rotation,
    sensitivity,
    turn,
    vector,
)
from nocs.devices import Coordinates, Location
from nocs.equipment import HorizonPoint, Role
from nocs.jobs import JobContext, JobManager
from nocs.mount.coords import sidereal_time
from nocs.mount.service import Frame, PointingError
from nocs.pointing.solve import FrameSolve, SolveOptions
from nocs.solving import Failure, SolveError
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("polar_alignment",)
POINTS = 3
RETRIES = 3
"""Frames taken again in place when one of the three points does not solve."""
MAX_POLE_DEC = 80.0
"""Degrees of |Dec| above which a start is refused: the circle is not much larger
than the field there, and that is where mounts park."""
MIN_SENSITIVITY = 0.2
"""Of the last point (``polar.sensitivity``): below it a solve's error would grow more
than five times in the knobs."""
TURN_CHECK = 2.0
"""Degrees the measured turn may differ from the one asked for before a warning."""
UPDATES = 60
"""Updates of the live phase kept in the state."""
FATAL = frozenset({Failure.UNAVAILABLE, Failure.NO_DATABASE})

type Side = Literal["auto", "east", "west"]


class Solves(Protocol):
    """``PointingService``."""

    def check(self, options: SolveOptions, role: Role = Role.MAIN_CAMERA) -> None: ...
    def resources(self, role: Role = Role.MAIN_CAMERA) -> list[str]: ...
    async def solve_frame(
        self, context: JobContext, options: SolveOptions, role: Role = Role.MAIN_CAMERA
    ) -> FrameSolve: ...


class Mounts(Protocol):
    """The mount role (``MountService``)."""

    def site(self) -> Location | None: ...
    def position_jnow(self) -> Coordinates: ...
    async def slew(
        self,
        context: JobContext,
        ra: float,
        dec: float,
        *,
        force: bool = False,
        frame: Frame = "j2000",
    ) -> Coordinates: ...
    async def settle(self, seconds: float) -> None: ...
    async def set_tracking(
        self, on: bool | None, mode: str | None = None, *, job: str | None = None
    ) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class PolarOptions:
    exposure: float | None = None
    """Seconds; the camera's solving exposure when ``None``."""
    binning: int | None = None
    step: float = 30.0
    """Degrees of each of the two turns of the RA axis."""
    side: Side = "auto"
    """Which way to turn: away from the meridian with ``auto``."""
    settle: float = 2.0
    """Seconds to wait after a turn."""
    tolerance: float = 1.0
    """Arcminutes of total error for "aligned"."""
    min_altitude: float = 20.0
    back: bool = True
    """Go back to the start when finishing."""

    def check(self) -> None:
        if not 10 <= self.step <= 60:
            raise ValueError("the turn must be 10..60°")
        if not 0 <= self.settle <= 60:
            raise ValueError("the settling time must be 0..60 s")
        if not 0 < self.tolerance <= 60:
            raise ValueError("the tolerance must be 0..60 arcminutes")
        if not 0 <= self.min_altitude <= 80:
            raise ValueError("the minimum altitude must be 0..80°")
        self.solve_options.check()

    @property
    def solve_options(self) -> SolveOptions:
        return SolveOptions(exposure=self.exposure, binning=self.binning)


class RunState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Phase(StrEnum):
    SOLVING = "solving"
    TURNING = "turning"
    SETTLING = "settling"
    ADJUSTING = "adjusting"
    RETURNING = "returning"


@dataclass
class Point:
    aim: Coordinates
    """JNow, where the mount was sent (the start: where it was)."""
    solve: FrameSolve | None = None
    direction: Vector | None = None
    failures: list[SolveError] = field(default_factory=lambda: list[SolveError]())


@dataclass
class Update:
    taken: datetime
    error: PolarError | None = None
    knobs: Knobs | None = None
    failure: SolveError | None = None


@dataclass
class _Run:
    job: str
    options: PolarOptions
    side: Literal["east", "west"]
    start: Coordinates
    latitude: float
    points: list[Point] = field(default_factory=lambda: list[Point]())
    rotation: list[float] = field(default_factory=lambda: list[float]())
    axis: Vector | None = None
    updates: list[Update] = field(default_factory=lambda: list[Update]())
    finish: anyio.Event = field(default_factory=anyio.Event)
    state: RunState = RunState.RUNNING
    phase: Phase | None = None
    warning: str | None = None
    error: str | None = None
    started: str = field(default_factory=lambda: _now())
    finished: str | None = None

    def summary(self) -> dict[str, Json]:
        error = polar_error(self.axis, self.latitude) if self.axis is not None else None
        o = self.options
        return {
            "job": self.job,
            "state": self.state.value,
            "phase": self.phase.value if self.phase else None,
            "options": {
                "exposure": o.exposure,
                "binning": o.binning,
                "step": o.step,
                "side": self.side,
                "tolerance": o.tolerance,
                "back": o.back,
            },
            "start": {"ra": self.start.ra, "dec": self.start.dec},
            "points": [_point(p) for p in self.points],
            "rotation": list(self.rotation),
            "axis": _error(error),
            "aligned": error is not None and error.total <= o.tolerance,
            "updates": [_update(u) for u in self.updates[-UPDATES:]],
            "warning": self.warning,
            "error": self.error,
            "started": self.started,
            "finished": self.finished,
        }


class PolarAlignmentService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        pointing: Solves,
        mount: Mounts,
        clock: Clock,
        horizon: Callable[[], list[HorizonPoint] | None] = lambda: None,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._pointing = pointing
        self._mount = mount
        self._clock = clock
        self._horizon = horizon
        self._run: _Run | None = None
        store.set(ROOT, None)

    def start(self, options: PolarOptions) -> str:
        """Start a polar alignment from where the mount points; returns the job id."""
        options.check()
        self._pointing.check(options.solve_options)
        resources = self._pointing.resources()
        self._jobs.check_free(resources)
        site, start, side = self.plan(options)

        async def job(context: JobContext) -> Json:
            return await self._align(context, options, site, start, side)

        return self._jobs.start("polar_align", resources, job)

    def plan(self, options: PolarOptions) -> tuple[Location, Coordinates, Literal["east", "west"]]:
        """Check a start where the mount points now; returns the site, the start (JNow)
        and the side the RA axis turns to. Raises ``PointingError`` or ``ValueError``."""
        site = self._mount.site()
        if site is None:
            raise PointingError("the site is unknown: set it in the profile")
        start = self._mount.position_jnow()
        if abs(start.dec) > MAX_POLE_DEC:
            raise ValueError(
                f"the mount points within {90 - MAX_POLE_DEC:g}° of the pole: "
                "start on the meridian, halfway between the zenith and the pole"
            )
        hour_angle = _hours(sidereal_time(site.longitude, self._clock.now()) - start.ra)
        side: Literal["east", "west"]
        side = ("west" if hour_angle >= 0 else "east") if options.side == "auto" else options.side
        sign = 1 if side == "west" else -1
        horizon = self._horizon()
        for number in range(POINTS):
            h = hour_angle + sign * number * options.step / 15
            if abs(h) > 12:
                raise ValueError(
                    f"turning {side} would take point {number + 1} under the pole: "
                    "start nearer the meridian or turn the other way"
                )
            alt, az = altaz(vector(h, start.dec), site.latitude)
            lowest = max(options.min_altitude, _horizon_at(horizon, az))
            if alt < lowest:
                raise ValueError(
                    f"point {number + 1} would be {alt:.0f}° high, under {lowest:.0f}°: "
                    "start nearer the meridian, higher, or turn the other way"
                )
        last = vector(hour_angle + sign * (POINTS - 1) * options.step / 15, start.dec)
        if sensitivity(last, pole(site.latitude), site.latitude) < MIN_SENSITIVITY:
            raise ValueError(
                "from here the frames would not tell the two knobs apart: start on the "
                "meridian, halfway between the zenith and the pole"
            )
        return site, start, side

    def finish(self) -> None:
        """End the live phase: back to the start (with ``back``) and succeed."""
        run = self._run
        if run is None or run.state is not RunState.RUNNING:
            raise ValueError("no polar alignment is running")
        if run.axis is None:
            raise ValueError("the axis is not measured yet: cancel to stop")
        run.finish.set()

    # -- internals ----------------------------------------------------------

    async def _align(
        self,
        context: JobContext,
        options: PolarOptions,
        site: Location,
        start: Coordinates,
        side: Literal["east", "west"],
    ) -> Json:
        run = _Run(context.id, options, side, start, site.latitude)
        self._run = run
        self._publish()
        try:
            await self._measure(context, run, site)
            await self._adjust(context, run, site)
            if options.back:
                run.phase = Phase.RETURNING
                self._report(context, run, "going back to the start")
                await self._mount.slew(context, start.ra, start.dec, frame="jnow")
        except BaseException as e:
            cancelled = isinstance(e, anyio.get_cancelled_exc_class())
            run.state = RunState.CANCELLED if cancelled else RunState.FAILED
            if not cancelled:
                run.error = str(e) or type(e).__name__
            raise
        else:
            run.state = RunState.SUCCEEDED
        finally:
            run.phase = None
            run.finished = _now()
            self._publish()
        return run.summary()

    async def _measure(self, context: JobContext, run: _Run, site: Location) -> None:
        options = run.options
        await self._mount.set_tracking(True, job=context.id)
        sign = -1 if run.side == "west" else 1  # turning west lowers the RA
        for number in range(POINTS):
            aim = Coordinates(
                (run.start.ra + sign * number * options.step / 15) % 24, run.start.dec
            )
            point = Point(aim)
            run.points.append(point)
            if number:
                run.phase = Phase.TURNING
                self._report(context, run, f"turning the RA axis {options.step:g}° {run.side}")
                await self._mount.slew(context, aim.ra, aim.dec, frame="jnow")
                run.phase = Phase.SETTLING
                self._report(context, run, "settling")
                await self._mount.settle(options.settle)
            while point.solve is None:
                run.phase = Phase.SOLVING
                self._report(context, run, f"solving point {number + 1} of {POINTS}")
                try:
                    solved = await self._pointing.solve_frame(context, options.solve_options)
                except SolveError as e:
                    if e.reason in FATAL or len(point.failures) >= RETRIES:
                        raise
                    log.info("polar alignment, point %d: %s", number + 1, e)
                    point.failures.append(e)
                    continue
                point.solve = solved
                s = solved.result.solution
                point.direction = direction(s.ra, s.dec, site, solved.taken)
        directions = [p.direction for p in run.points if p.direction is not None]
        run.axis = fit_axis(directions, site.latitude)
        # The turns asked for: what the axis turned between frames, less the tracking.
        times = [p.solve.taken for p in run.points if p.solve is not None]
        run.rotation = [
            (rotation(run.axis, a, b) - math.degrees(SIDEREAL_RATE * (t1 - t0).total_seconds()))
            * (1 if run.side == "west" else -1)
            for (a, b), (t0, t1) in zip(
                itertools.pairwise(directions), itertools.pairwise(times), strict=True
            )
        ]
        off = max(abs(r - options.step) for r in run.rotation)
        if off > TURN_CHECK:
            run.warning = (
                f"the RA axis turned {', '.join(f'{r:.1f}°' for r in run.rotation)} instead of "
                f"{options.step:g}°: the Dec axis may have moved, and the error be off"
            )
        error = polar_error(run.axis, site.latitude)
        log.info(
            "polar alignment: axis %.1f' %s, %.1f' %s of the pole (%.1f')",
            abs(error.altitude),
            "above" if error.altitude >= 0 else "below",
            abs(error.azimuth),
            "east" if error.azimuth >= 0 else "west",
            error.total,
        )

    async def _adjust(self, context: JobContext, run: _Run, site: Location) -> None:
        assert run.axis is not None
        last = run.points[-1]
        assert last.solve is not None
        assert last.direction is not None
        previous, taken = last.direction, last.solve.taken
        run.phase = Phase.ADJUSTING
        while not run.finish.is_set():
            self._report(context, run, "turn the knobs; finish when aligned")
            try:
                solved = await self._pointing.solve_frame(context, run.options.solve_options)
            except SolveError as e:
                if e.reason in FATAL:
                    raise
                run.updates.append(
                    Update(self._clock.now(), polar_error(run.axis, site.latitude), failure=e)
                )
                continue
            s = solved.result.solution
            here = direction(s.ra, s.dec, site, solved.taken)
            seconds = (solved.taken - taken).total_seconds()
            turned = knobs(previous, here, run.axis, site.latitude, seconds)
            run.axis = turn(
                run.axis, run.axis, site.latitude, altitude=turned.altitude, azimuth=turned.azimuth
            )
            run.updates.append(Update(solved.taken, polar_error(run.axis, site.latitude), turned))
            del run.updates[:-UPDATES]
            previous, taken = here, solved.taken

    def _report(self, context: JobContext, run: _Run, message: str) -> None:
        context.progress(None, message)
        self._publish()

    def _publish(self) -> None:
        if self._run is not None:
            self._store.set(ROOT, self._run.summary())


def _horizon_at(horizon: list[HorizonPoint] | None, azimuth: float) -> float:
    if not horizon:
        return 0.0
    return float(
        np.interp(
            azimuth,
            [p.azimuth for p in horizon],
            [p.altitude for p in horizon],
            period=360,
        )
    )


def _hours(h: float) -> float:
    """An hour angle in -12..12."""
    return (h + 12) % 24 - 12


def _error(error: PolarError | None) -> dict[str, Json] | None:
    if error is None:
        return None
    return {"altitude": error.altitude, "azimuth": error.azimuth, "total": error.total}


def _failure(e: SolveError) -> dict[str, Json]:
    return {"reason": e.reason.value, "message": str(e)}


def _point(point: Point) -> dict[str, Json]:
    solved = point.solve
    hour_angle, dec = angles(point.direction) if point.direction is not None else (None, None)
    return {
        "aim": {"ra": point.aim.ra, "dec": point.aim.dec},
        "solution": (
            {"ra": solved.result.solution.ra, "dec": solved.result.solution.dec} if solved else None
        ),
        "hour_angle": hour_angle,
        "dec": dec,
        "taken": solved.taken.isoformat(timespec="milliseconds") if solved else None,
        "failures": [_failure(e) for e in point.failures],
    }


def _update(update: Update) -> dict[str, Json]:
    k = update.knobs
    return {
        "taken": update.taken.isoformat(timespec="milliseconds"),
        "axis": _error(update.error),
        "knobs": ({"altitude": k.altitude, "azimuth": k.azimuth} if k else None),
        "failure": _failure(update.failure) if update.failure else None,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
