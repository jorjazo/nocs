"""Centre a target: go to it, solve where the frame landed, correct, and again.

``CenteringService.center`` works inside any job that holds the camera and the
mount, so re-centring after a meridian flip and sequences call it from their own;
``start`` runs it in a ``center`` job of its own for the API. Each attempt:

1. goes to where it aims (the target, at first) and waits for the mount to settle;
2. takes and solves a frame (``PointingService.solve_frame``), and with the
   ``sync`` method syncs the mount to it;
3. measures the error, from the target to the solution; within the tolerance, done;
4. else aims again: at the target with ``sync`` (the mount now knows where it
   points), or with ``offset`` at the last aim moved by the error, for mounts that
   should not be synced (after a meridian flip, say).

A frame that does not solve (no stars, no solution) counts as an attempt and is
taken again without moving; no ASTAP or no star database ends the run at once.

State under ``("centering",)``: ``None`` until the first run, then that run as it
goes (the most recent one, finished or not)::

    {job, state, phase, method, target, tolerance, max_attempts, attempts, error,
     started, finished}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

import anyio

from nocs.devices import Coordinates
from nocs.equipment import Role
from nocs.jobs import JobContext, JobManager
from nocs.pointing.solve import FrameSolve, Offset, PointingService, SolveOptions, offset
from nocs.solving import Failure, SolveError
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("centering",)
MAX_ATTEMPTS = 20
FATAL = frozenset({Failure.UNAVAILABLE, Failure.NO_DATABASE})
"""Solve failures that another frame would only repeat."""

type Method = Literal["sync", "offset"]


class CenteringError(Exception):
    """The target was not centred within the tolerance in the attempts allowed."""


class Mounts(Protocol):
    """The mount role (``MountService``)."""

    def check_goto(self, ra: float, dec: float, *, force: bool = False) -> None: ...
    async def slew(
        self, context: JobContext, ra: float, dec: float, *, force: bool = False
    ) -> Coordinates: ...
    async def settle(self, seconds: float) -> None: ...


@dataclass(frozen=True, slots=True)
class CenterOptions:
    tolerance: float = 1.0
    """Arcminutes from the target the frame's centre may be."""
    attempts: int = 5
    """Frames to take at most, those that fail to solve included."""
    settle: float = 2.0
    """Seconds to wait after a slew before the frame."""
    method: Method = "sync"
    exposure: float | None = None
    """Seconds; the camera's current exposure when ``None``."""
    binning: int | None = None
    force: bool = False
    """Go below the horizon."""

    def check(self) -> None:
        if not 0 < self.tolerance <= 60:
            raise ValueError("the tolerance must be 0..60 arcminutes")
        if not 1 <= self.attempts <= MAX_ATTEMPTS:
            raise ValueError(f"the attempts must be 1..{MAX_ATTEMPTS}")
        if not 0 <= self.settle <= 60:
            raise ValueError("the settling time must be 0..60 s")
        self.solve_options.check()

    @property
    def solve_options(self) -> SolveOptions:
        return SolveOptions(
            exposure=self.exposure, binning=self.binning, sync=self.method == "sync"
        )


@dataclass(frozen=True, slots=True)
class Attempt:
    aim: Coordinates
    """Where the mount was sent, J2000."""
    solve: FrameSolve | None = None
    error: Offset | None = None
    """From the target to the frame's centre."""
    failure: SolveError | None = None


class RunState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Phase(StrEnum):
    SLEWING = "slewing"
    SETTLING = "settling"
    SOLVING = "solving"


@dataclass(slots=True)
class _Run:
    job: str
    target: Coordinates
    options: CenterOptions
    started: str = field(default_factory=lambda: _now())
    state: RunState = RunState.RUNNING
    phase: Phase = Phase.SLEWING
    attempts: list[Attempt] = field(default_factory=list[Attempt])
    error: str | None = None
    finished: str | None = None

    def summary(self) -> dict[str, Json]:
        return {
            "job": self.job,
            "state": self.state.value,
            "phase": self.phase.value if self.state is RunState.RUNNING else None,
            "method": self.options.method,
            "target": {"ra": self.target.ra, "dec": self.target.dec},
            "tolerance": self.options.tolerance,
            "max_attempts": self.options.attempts,
            "attempts": [_attempt(a) for a in self.attempts],
            "error": self.error,
            "started": self.started,
            "finished": self.finished,
        }


class CenteringService:
    def __init__(
        self, store: StateStore, jobs: JobManager, pointing: PointingService, mount: Mounts
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._pointing = pointing
        self._mount = mount
        self._run: _Run | None = None
        store.set(ROOT, None)

    def start(
        self, ra: float, dec: float, options: CenterOptions, role: Role = Role.MAIN_CAMERA
    ) -> str:
        """Centre J2000 ``ra``, ``dec`` in a job of its own; returns the job id.

        It locks what a solve does: the camera (with the main camera, the filter
        wheel and the focuser) and the mount.
        """
        options.check()
        self._pointing.check(options.solve_options, role)
        self._mount.check_goto(ra, dec, force=options.force)
        resources = self._pointing.resources(role)
        self._jobs.check_free(resources)

        async def job(context: JobContext) -> Json:
            return await self.center(context, ra, dec, options, role)

        return self._jobs.start("center", resources, job)

    async def center(
        self,
        context: JobContext,
        ra: float,
        dec: float,
        options: CenterOptions,
        role: Role = Role.MAIN_CAMERA,
    ) -> dict[str, Json]:
        """Centre J2000 ``ra``, ``dec`` inside ``context``'s job, which must hold the
        camera and the mount; returns the run's summary.

        Raises ``CenteringError`` when the attempts run out, ``SolveError`` when
        frames cannot be solved at all.
        """
        options.check()
        run = _Run(context.id, Coordinates(ra, dec), options)
        self._run = run
        self._publish()
        try:
            await self._center(context, run, role)
        except BaseException as e:
            cancelled = isinstance(e, anyio.get_cancelled_exc_class())
            run.state = RunState.CANCELLED if cancelled else RunState.FAILED
            if not cancelled:
                run.error = str(e) or type(e).__name__
            raise
        else:
            run.state = RunState.SUCCEEDED
        finally:
            run.finished = _now()
            self._publish()
        return run.summary()

    # -- internals ----------------------------------------------------------

    async def _center(self, context: JobContext, run: _Run, role: Role) -> None:
        options = run.options
        target = run.target
        aim = target
        move = True
        total = options.attempts

        def report(message: str) -> None:
            context.progress(len(run.attempts) / total, message)
            self._publish()

        for number in range(1, total + 1):
            prefix = f"attempt {number} of {total}"
            if move:
                run.phase = Phase.SLEWING
                report(f"{prefix}: slewing")
                await self._mount.slew(context, aim.ra, aim.dec, force=options.force)
                run.phase = Phase.SETTLING
                report(f"{prefix}: settling")
                await self._mount.settle(options.settle)
            run.phase = Phase.SOLVING
            report(f"{prefix}: solving")
            try:
                solved = await self._pointing.solve_frame(context, options.solve_options, role)
            except SolveError as e:
                if e.reason in FATAL:
                    raise
                log.info("centring, %s: %s", prefix, e)
                run.attempts.append(Attempt(aim, failure=e))
                report(f"{prefix}: not solved ({e.reason.value})")
                move = False
                continue
            solution = solved.result.solution
            error = offset(target.ra, target.dec, solution.ra, solution.dec)
            run.attempts.append(Attempt(aim, solved, error))
            log.info("centring, %s: %.2f arcminutes from the target", prefix, error.angle)
            report(f"{prefix}: {error.angle:.1f} arcminutes from the target")
            if error.angle <= options.tolerance:
                return
            if options.method == "offset":
                aim = _corrected(aim, target, Coordinates(solution.ra, solution.dec))
            move = True
        last = next((a.error for a in reversed(run.attempts) if a.error is not None), None)
        raise CenteringError(
            f"still {last.angle:.1f} arcminutes from the target after {total} attempts"
            if last is not None
            else f"none of {total} frames solved"
        )

    def _publish(self) -> None:
        if self._run is not None:
            self._store.set(ROOT, self._run.summary())


def _corrected(aim: Coordinates, target: Coordinates, landed: Coordinates) -> Coordinates:
    """``aim`` moved by what the frame missed the target by (RA in hours)."""
    hours = (target.ra - landed.ra + 12) % 24 - 12
    dec = min(max(aim.dec + target.dec - landed.dec, -90.0), 90.0)
    return Coordinates((aim.ra + hours) % 24, dec)


def _attempt(attempt: Attempt) -> dict[str, Json]:
    solved = attempt.solve
    error = attempt.error
    failure = attempt.failure
    return {
        "aim": {"ra": attempt.aim.ra, "dec": attempt.aim.dec},
        "solution": (
            {"ra": solved.result.solution.ra, "dec": solved.result.solution.dec} if solved else None
        ),
        "error": {"angle": error.angle, "ra": error.ra, "dec": error.dec} if error else None,
        "synced": solved.synced if solved else False,
        "failure": ({"reason": failure.reason.value, "message": str(failure)} if failure else None),
    }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
