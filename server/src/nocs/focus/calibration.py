"""Focuser calibration: backlash each way, an overshoot that returns, the scale (ADR 0044).

A calibration runs in a job of its own that locks what autofocus locks, and:

1. refuses a driver that compensates backlash itself;
2. focuses (autofocus, with a large overshoot): the curve's best focus ``c``,
   best HFR ``a`` and width ``b``;
3. makes a ruler of frames on the arm past the best focus, on the approach side,
   from 1.2 ``b`` to 5 ``b``, each reached moving that way;
4. reverses, twice each way, in chunks small enough to keep the optics on the arm,
   until a frame shows them moving: the motion lost is the commanded steps less
   the ones measured; one more chunk checks that the optics follow the motor;
5. checks round trips: three times, from the arm's far end, approaches a position
   on the arm as autofocus does with an overshoot of 1.3 times the largest motion
   lost, and finds the optics there; a miss raises the overshoot by half;
6. approaches the best focus with that overshoot, and keeps the result with the
   focuser's settings (its overshoot becomes the focuser's).

A failed or cancelled calibration goes back to the best focus once it is known,
with the large overshoot.

State under ``("focus_calibration",)``: ``None`` until the first one, then that one
as it goes::

    {job, state, phase, started, finished, start_position, direction, best, ruler,
     reversals, overshoot, trips, noise, min_step, microns_per_step, focus_zone,
     suggested_step, slip, hfr, problem, detail}
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

import anyio

from nocs.devices import DeviceError, FrameType
from nocs.equipment import Role
from nocs.focus.autofocus import (
    RESOURCES,
    AutofocusError,
    AutofocusOptions,
    AutofocusService,
    FocuserDevice,
    Frames,
    settle,
)
from nocs.focus.backlash import (
    Ruler,
    RulerError,
    focus_zone,
    microns_per_step,
    min_step,
    overshoot_for,
    round_up,
)
from nocs.focus.focusers import FocuserCalibration, FocuserConfig
from nocs.focus.service import FocuserNotReadyError
from nocs.focus.sweep import Direction, approach
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("focus_calibration",)

RULER = (1.2, 1.96, 2.72, 3.48, 4.24, 5.0)
"""Where the ruler's frames are, in widths ``b`` past the best focus."""
NEAR = 1.2
"""The arm's end towards focus, in widths: the optics never go closer."""
FAR = 5.0
"""The arm's far end, in widths."""
BEYOND = 5.5
"""How far out the optics may go while reversing outward, in widths."""
CHUNK = 2.5
"""The largest move while reversing, in widths: the optics cannot cross focus."""
MAX_SLACK = 6000
"""Steps without the optics moving after which the focuser counts as not moving them."""
FOLLOW = 0.6
"""The least fraction of the motor's move the optics must follow once they move."""
RAISE = 1.5
"""How much a missed round trip raises the overshoot."""
TRIPS = (3.0, 2.0, 4.0)
"""Round trips' targets, in widths past the best focus."""
ATTEMPTS = 3
ROUNDS = 2
"""Reversals each way."""
RESET = 2000
"""The least overshoot for autofocus and for going back: larger than any backlash seen."""


class Problem(StrEnum):
    DRIVER_BACKLASH = "driver_backlash"
    """The driver compensates backlash itself."""
    AUTOFOCUS = "autofocus"
    """Autofocus failed (its own problem in ``detail``)."""
    TOO_FEW_STARS = "too_few_stars"
    """A frame on the arm had too few stars."""
    NOT_AN_ARM = "not_an_arm"
    """The ruler's frames do not grow steadily away from focus."""
    NO_MOVEMENT = "no_movement"
    """The optics never moved after a reversal."""
    TRAVEL = "travel"
    """The calibration would leave the focuser's travel."""
    NOT_REPEATABLE = "not_repeatable"
    """The round trips kept missing their targets, even with larger overshoots."""


class Phase(StrEnum):
    FOCUSING = "focusing"
    RULER = "ruler"
    REVERSING = "reversing"
    ROUND_TRIPS = "round_trips"
    RETURNING = "returning"
    RESTORING = "restoring"


class State(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CalibrationError(Exception):
    def __init__(self, problem: Problem, detail: str) -> None:
        super().__init__(detail)
        self.problem = problem


class Focusers(Protocol):
    """The focuser role (``FocuserService``)."""

    def focuser(self) -> CalibratedFocuser: ...
    def backlash(self) -> FocuserConfig: ...
    def set_calibration(self, calibration: FocuserCalibration) -> None: ...


class CalibratedFocuser(FocuserDevice, Protocol):
    @property
    def driver_backlash(self) -> int | None: ...


@dataclass(frozen=True, slots=True)
class Scale:
    """What turns the V's slope into microns: the train's focal ratio, the pixel size."""

    focal_ratio: float
    pixel_size: float
    """Micrometres, unbinned."""


@dataclass(frozen=True, slots=True)
class Reversal:
    towards: Direction
    lost: int
    slip: bool


@dataclass(frozen=True, slots=True)
class Trip:
    target: int
    measured: float | None
    ok: bool
    overshoot: int


@dataclass(slots=True)
class _Run:
    job: str
    options: AutofocusOptions
    start_position: int
    started: str = field(default_factory=lambda: _now())
    state: State = State.RUNNING
    phase: Phase = Phase.FOCUSING
    best: tuple[int, float, float] | None = None
    """Position, best HFR ``a`` and width ``b``."""
    suggested_step: int | None = None
    ruler_points: list[tuple[int, float | None, int]] = field(
        default_factory=list[tuple[int, float | None, int]]
    )
    ruler: Ruler | None = None
    reversals: list[Reversal] = field(default_factory=list[Reversal])
    overshoot: int | None = None
    trips: list[Trip] = field(default_factory=list[Trip])
    microns: float | None = None
    zone: int | None = None
    hfr: float | None = None
    """At the best focus, at the end."""
    problem: Problem | None = None
    detail: str | None = None
    finished: str | None = None

    def summary(self) -> dict[str, Json]:
        ruler = self.ruler
        return {
            "job": self.job,
            "state": self.state.value,
            "phase": self.phase.value if self.state is State.RUNNING else None,
            "started": self.started,
            "finished": self.finished,
            "start_position": self.start_position,
            "direction": _name(self.options.direction),
            "best": (
                {"position": self.best[0], "hfr": self.best[1], "width": self.best[2]}
                if self.best
                else None
            ),
            "ruler": [
                {"position": position, "hfr": hfr, "stars": stars}
                for position, hfr, stars in self.ruler_points
            ],
            "reversals": [
                {"towards": _name(r.towards), "lost": r.lost, "slip": r.slip}
                for r in self.reversals
            ],
            "overshoot": self.overshoot,
            "trips": [
                {
                    "target": t.target,
                    "measured": None if t.measured is None else round(t.measured),
                    "ok": t.ok,
                    "overshoot": t.overshoot,
                }
                for t in self.trips
            ],
            "noise": round(ruler.noise, 1) if ruler else None,
            "min_step": min_step(ruler.noise) if ruler else None,
            "microns_per_step": round(self.microns, 3) if self.microns is not None else None,
            "focus_zone": self.zone,
            "suggested_step": self.suggested_step,
            "slip": any(r.slip for r in self.reversals),
            "hfr": self.hfr,
            "problem": self.problem.value if self.problem else None,
            "detail": self.detail,
        }


class FocuserCalibrationService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        focuser: Focusers,
        capture: Frames,
        autofocus: AutofocusService,
        *,
        scale: Callable[[], Scale | None] = lambda: None,
        profile: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._focuser = focuser
        self._capture = capture
        self._autofocus = autofocus
        self._scale = scale
        self._profile = profile
        self._run: _Run | None = None
        store.set(ROOT, None)

    def options(
        self, *, step: int | None = None, exposure: float | None = None
    ) -> AutofocusOptions:
        """Autofocus's options for the calibration: the train's sweep, a large overshoot."""
        options = self._autofocus.options(step=step, exposure=exposure)
        saved = self._focuser.backlash().overshoot or 0
        return replace(options, overshoot=max(RESET, 3 * saved))

    def start(self, options: AutofocusOptions) -> str:
        """Calibrate in a job of its own; returns the job id."""
        options.check()
        focuser = self._focuser.focuser()  # fail now, not in the job, without a focuser
        self._capture.camera(Role.MAIN_CAMERA)
        self._jobs.check_free(RESOURCES)
        if (steps := focuser.driver_backlash) is not None:
            raise ValueError(_driver_detail(steps))

        async def job(context: JobContext) -> Json:
            return await self.run(context, options)

        return self._jobs.start("focus_calibration", RESOURCES, job)

    async def run(self, context: JobContext, options: AutofocusOptions) -> dict[str, Json]:
        """Calibrate inside ``context``'s job, which must hold what autofocus needs."""
        focuser = self._focuser.focuser()
        run = _Run(context.id, options, focuser.position)
        self._run = run
        self._publish()
        try:
            await self._calibrate(context, focuser, run)
        except BaseException as e:
            run.state = State.CANCELLED if _cancelled(e) else State.FAILED
            if isinstance(e, CalibrationError):
                run.problem, run.detail = e.problem, str(e)
            elif not _cancelled(e):
                run.detail = str(e) or type(e).__name__
            await self._restore(context, focuser, run)
            raise
        else:
            run.state = State.SUCCEEDED
        finally:
            run.finished = _now()
            self._publish()
        return run.summary()

    # -- internals ----------------------------------------------------------

    async def _calibrate(self, context: JobContext, focuser: CalibratedFocuser, run: _Run) -> None:
        options = run.options
        if (steps := focuser.driver_backlash) is not None:
            raise CalibrationError(Problem.DRIVER_BACKLASH, _driver_detail(steps))
        side = options.direction
        maximum = focuser.max_position
        criteria = options.criteria

        # 1. Focus.
        context.progress(0.0, "focusing")
        try:
            focused = await self._autofocus.run(_Part(context, 0.0, 0.4), options)
        except AutofocusError as e:
            raise CalibrationError(Problem.AUTOFOCUS, f"autofocus: {e}") from e
        fit = focused.get("fit")
        assert isinstance(fit, dict)
        a, b, c = (_float(fit[k]) for k in ("a", "b", "c"))
        best = round(c)
        run.best = (best, round(a, 3), round(b, 1))
        step = focused.get("suggested_step")
        run.suggested_step = step if isinstance(step, int) else None
        width = b

        def arm(widths: float) -> int:
            return round(c + side * widths * width)

        def report(fraction: float, message: str) -> None:
            context.progress(fraction, message)
            self._publish()

        async def go(position: int) -> None:
            if position < 0 or (maximum is not None and position > maximum):
                raise CalibrationError(
                    Problem.TRAVEL,
                    f"position {position} is outside the focuser's travel (0..{maximum})",
                )
            await focuser.move_to(position)

        async def frame(label: str) -> tuple[float | None, int]:
            shot = await self._capture.take(
                context, Role.MAIN_CAMERA, options.exposure, FrameType.LIGHT, label
            )
            metrics = await self._capture.measure(shot)
            return metrics.hfr, metrics.stars

        async def where(label: str) -> float:
            """Where the optics are, from a frame on the arm."""
            hfr, stars = await frame(label)
            if hfr is None or stars < criteria.min_stars:
                raise CalibrationError(
                    Problem.TOO_FEW_STARS,
                    f"{stars} stars at {focuser.position} ({criteria.min_stars} needed)",
                )
            assert run.ruler is not None
            return run.ruler.position(hfr)

        # 2. The ruler, every frame reached moving the approach way (as autofocus left it).
        run.phase = Phase.RULER
        for i, widths in enumerate(RULER):
            position = arm(widths)
            report(0.4 + 0.1 * i / len(RULER), f"ruler: {position}")
            await go(position)
            hfr, stars = await frame(f"ruler {position}: ")
            run.ruler_points.append((position, hfr, stars))
        usable = [
            (p, h) for p, h, s in run.ruler_points if h is not None and s >= criteria.min_stars
        ]
        if len(usable) < len(RULER) - 1:
            raise CalibrationError(
                Problem.TOO_FEW_STARS,
                f"only {len(usable)} of {len(RULER)} frames on the arm had"
                f" {criteria.min_stars} stars or more",
            )
        try:
            run.ruler = ruler = Ruler.fit([p for p, _ in usable], [h for _, h in usable])
        except RulerError as e:
            raise CalibrationError(Problem.NOT_AN_ARM, str(e)) from e
        threshold = max(4 * ruler.noise, 0.25 * width, 2.0)
        log.info(
            "focuser calibration: best %d (a %.2f, b %.1f); ruler noise %.1f steps",
            best,
            a,
            b,
            ruler.noise,
        )

        async def reverse(towards: Direction, ref: float, limit: float, jump: int) -> float:
            """Move ``towards`` until the optics move; record the motion lost.

            Returns where the optics are then. ``ref`` is where they are now, ``limit``
            how far they may go that way.
            """
            cumulative = 0
            first = True
            while True:
                room = abs(limit - ref)
                chunk = max(1, int(min(CHUNK * width, room)))
                if first and jump > 0:
                    chunk = jump
                first = False
                cumulative += chunk
                # A chunk past the slack on a wide curve (the simulators': b ~6000) is
                # not motion lost: count only what lies beyond one chunk.
                if cumulative > MAX_SLACK + CHUNK * width:
                    raise CalibrationError(
                        Problem.NO_MOVEMENT,
                        f"the optics did not move over {MAX_SLACK} steps {_name(towards)}:"
                        " is the focuser's motor coupled to the drawtube?",
                    )
                await go(focuser.position + towards * chunk)
                now = await where(f"{_name(towards)} {focuser.position}: ")
                moved = (now - ref) * towards
                if moved <= threshold:
                    continue
                # The ruler's noise can measure more motion than was commanded; lost
                # motion is never negative.
                lost = max(0, round(cumulative - moved))
                # One more chunk: the optics should follow the motor now.
                confirm = int(min(width, abs(limit - now)))
                slip = False
                if confirm > threshold:
                    await go(focuser.position + towards * confirm)
                    after = await where(f"{_name(towards)} {focuser.position}: ")
                    slip = (after - now) * towards < FOLLOW * confirm
                    now = after
                run.reversals.append(Reversal(towards, lost, slip))
                log.info(
                    "focuser calibration: %d steps lost reversing %s%s",
                    lost,
                    _name(towards),
                    " (the optics slip)" if slip else "",
                )
                self._publish()
                return now

        async def bring(target: int, now: float, towards: Direction) -> float:
            """In contact moving ``towards``: move the optics from ``now`` to ``target``."""
            distance = round((target - now) * towards)
            if distance <= threshold:
                return now
            await go(focuser.position + towards * distance)
            return await where(f"{_name(towards)} {focuser.position}: ")

        # 3. Reversals: back towards focus, then out again.
        run.phase = Phase.REVERSING
        back = Direction(-side)
        now = float(arm(FAR))
        jumps = {back: 0, side: 0}
        for i in range(ROUNDS):
            report(0.5 + 0.25 * i / ROUNDS, f"reversing {_name(back)}")
            now = await reverse(back, now, arm(NEAR), jumps[back])
            jumps[back] = _jump(run.reversals[-1].lost, width)
            now = await bring(arm(1.5), now, back)
            report(0.5 + 0.25 * (i + 0.5) / ROUNDS, f"reversing {_name(side)}")
            now = await reverse(side, now, arm(BEYOND), jumps[side])
            jumps[side] = _jump(run.reversals[-1].lost, width)
            now = await bring(arm(FAR), now, side)

        # 4. Round trips with the overshoot.
        run.phase = Phase.ROUND_TRIPS
        overshoot = overshoot_for([r.lost for r in run.reversals], options.step)
        tolerance = max(4 * ruler.noise, 0.3 * width, 2.0)
        for attempt in range(ATTEMPTS):
            run.overshoot = overshoot
            missed = False
            for widths in TRIPS:
                target = arm(widths)
                report(0.75 + 0.15 * attempt / ATTEMPTS, f"round trip to {target}")
                await go(arm(FAR))
                for position in approach(focuser.position, target, side, overshoot, maximum):
                    await go(position)
                hfr, stars = await frame(f"round trip {target}: ")
                measured = (
                    ruler.position(hfr) if hfr is not None and stars >= criteria.min_stars else None
                )
                ok = measured is not None and abs(measured - target) <= tolerance
                run.trips.append(Trip(target, measured, ok, overshoot))
                self._publish()
                if not ok:
                    missed = True
                    break
            if not missed:
                break
            if attempt == ATTEMPTS - 1:
                raise CalibrationError(
                    Problem.NOT_REPEATABLE,
                    f"round trips missed their targets by more than {tolerance:.0f} steps,"
                    f" even with an overshoot of {overshoot}",
                )
            overshoot = round_up(overshoot * RAISE)
            log.info("focuser calibration: a round trip missed; overshoot %d", overshoot)

        # 5. Back to focus; the scale; keep it.
        run.phase = Phase.RETURNING
        report(0.92, f"back to {best}")
        for position in approach(focuser.position, best, side, overshoot, maximum):
            await go(position)
        hfr, _ = await frame("best focus: ")
        run.hfr = hfr
        if (scale := self._scale()) is not None:
            run.microns = microns_per_step(a, b, scale.focal_ratio, scale.pixel_size)
            run.zone = focus_zone(scale.focal_ratio, run.microns)
        self._focuser.set_calibration(
            FocuserCalibration(
                measured=_now(),
                profile=self._profile(),
                inward=[r.lost for r in run.reversals if r.towards is Direction.INWARD],
                outward=[r.lost for r in run.reversals if r.towards is Direction.OUTWARD],
                overshoot=overshoot,
                noise=round(ruler.noise, 1),
                min_step=min_step(ruler.noise),
                microns_per_step=round(run.microns, 3) if run.microns is not None else None,
                focus_zone=run.zone,
                slip=any(r.slip for r in run.reversals),
            )
        )
        context.progress(1.0, f"calibrated: overshoot {overshoot}")

    async def _restore(self, context: JobContext, focuser: FocuserDevice, run: _Run) -> None:
        """Back to the best focus once known; never raises.

        Autofocus goes back to where it started when it fails itself.
        """
        if run.best is None:
            return
        run.phase = Phase.RESTORING
        self._publish()
        target = run.best[0]
        overshoot = 2 * (run.overshoot or 0) or run.options.overshoot or RESET
        with anyio.CancelScope(shield=True):
            try:
                if focuser.can_abort:
                    await focuser.abort()
                await settle(focuser)
                context.progress(None, f"back to {target}")
                for position in approach(
                    focuser.position,
                    target,
                    run.options.direction,
                    overshoot,
                    focuser.max_position,
                ):
                    try:
                        await focuser.move_to(position)
                    except DeviceError as e:
                        log.warning(
                            "calibration: moving back to %d refused, again: %s", position, e
                        )
                        await settle(focuser)
                        await focuser.move_to(position)
            except (DeviceError, ConnectionError, TimeoutError, FocuserNotReadyError) as e:
                log.error("calibration: could not move the focuser back: %s", e)

    def _publish(self) -> None:
        if self._run is not None:
            self._store.set(ROOT, self._run.summary())


class _Part(JobContext):
    """A job's context whose progress covers ``start`` to ``end`` of the whole."""

    def __init__(self, context: JobContext, start: float, end: float) -> None:
        self.id = context.id
        self._context = context
        self._start = start
        self._end = end

    def progress(self, fraction: float | None, message: str | None = None) -> None:
        scaled = None if fraction is None else self._start + fraction * (self._end - self._start)
        self._context.progress(scaled, message)


def _jump(lost: int, width: float) -> int:
    """A first move for the next reversal the same way: within the slack found."""
    return max(0, round(lost - CHUNK * width))


def _driver_detail(steps: int) -> str:
    return (
        f"the focuser's driver compensates {steps} steps of backlash itself: turn that off"
        " so that NOCS alone takes it up"
    )


def _name(direction: Direction) -> str:
    return "outward" if direction is Direction.OUTWARD else "inward"


def _float(value: Json) -> float:
    assert isinstance(value, int | float)
    return float(value)


def _cancelled(error: BaseException) -> bool:
    return isinstance(error, anyio.get_cancelled_exc_class())


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
