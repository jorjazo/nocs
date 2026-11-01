"""The flats wizard: each filter's exposure found by itself, on a panel or the sky (ADR 0036).

Every frame is measured before it is kept: its level (the median of its strongest
Bayer channel, above the pedestal of a shortest exposure) decides whether it is
saved and what the next exposure is. On a panel the light is steady, so the
exposure is scaled linearly to the target; on the twilight sky it changes by the
second, so the next exposure also follows the brightness trend of the last frames.

``FlatsService.run`` works inside any job that holds the main camera, the filter
wheel and the focuser (and the mount, for the sky); ``start`` is that job.

State under ``("flats",)``: the plan's source and target, and per filter its
exposure, last level, frames kept and how it went.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

import anyio
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nocs.calibration import twilight
from nocs.devices import Coordinates, FrameType, Location
from nocs.equipment import Role
from nocs.imaging import CameraSettings, Shot
from nocs.imaging.capture import Captured
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, StateStore

log = logging.getLogger(__name__)

ROOT = ("flats",)
CAMERA = Role.MAIN_CAMERA
FULL_SCALE = 65535.0
SATURATED = 0.95 * FULL_SCALE
DARK = 0.01 * FULL_SCALE
"""Signal below this tells nothing about the light: try ten times longer."""
MAX_MISSES = 8
"""Frames out of the band in a row before a filter gives up."""
SKY_WAIT = 20.0
"""Seconds between looks at a twilight sky not ready yet."""
OVERHEAD = 2.0
"""Seconds between two frames' exposures (download, measure), for the sky's trend."""


class FlatsError(Exception):
    pass


class FlatFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: str | None = Field(default=None, description="None: whatever the wheel holds.")
    count: int = Field(default=20, ge=1, le=200)
    focus: int | None = Field(
        default=None, ge=0, description="Focuser position for this filter's flats (the lights')."
    )


class FlatPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["panel", "sky"] = "panel"
    filters: list[FlatFilter] = Field(min_length=1)
    level: float = Field(default=0.5, ge=0.1, le=0.9, description="Fraction of full scale.")
    tolerance: float = Field(
        default=0.1, gt=0, le=0.5, description="Accepted fraction around the level."
    )
    min_exposure: float = Field(default=0.01, gt=0, le=60, description="Seconds.")
    max_exposure: float = Field(default=60, gt=0, le=600, description="Seconds.")
    start_exposure: float | None = Field(
        default=None, gt=0, le=600, description="First try; 1 s on a panel, 0.5 s on the sky."
    )
    gain: float | None = None
    offset: float | None = None
    binning: int | None = Field(default=None, ge=1, le=8)

    @model_validator(mode="after")
    def _limits(self) -> FlatPlan:
        if self.min_exposure >= self.max_exposure:
            raise ValueError("the shortest exposure must be below the longest")
        return self

    @property
    def target(self) -> float:
        return self.level * FULL_SCALE


# -- the exposure, from the levels ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class Sample:
    exposure: float
    level: float
    time: float
    """Monotonic seconds at the middle of the exposure."""


def brightness(sample: Sample, pedestal: float) -> float:
    """ADU per second above the pedestal."""
    return max(sample.level - pedestal, 0.0) / sample.exposure


def next_exposure(
    last: Sample,
    pedestal: float,
    target: float,
    *,
    trend: float = 1.0,
    ahead: float = 0.0,
) -> float:
    """The exposure that should put the next frame at ``target``.

    ``trend`` is the factor the brightness changes by per second (1 on a panel),
    ``ahead`` the seconds from the last frame's middle to the next one's. A clipped
    frame divides by ten, a black one multiplies by ten.
    """
    if last.level >= SATURATED:
        return last.exposure / 10
    if last.level - pedestal < DARK:
        return last.exposure * 10
    expected = brightness(last, pedestal) * trend**ahead
    return (target - pedestal) / expected


def trend_of(samples: list[Sample], pedestal: float) -> float:
    """Brightness change per second from the last two kept frames (1 without them)."""
    if len(samples) < 2:
        return 1.0
    a, b = samples[-2], samples[-1]
    if b.time <= a.time or brightness(a, pedestal) <= 0 or brightness(b, pedestal) <= 0:
        return 1.0
    ratio = brightness(b, pedestal) / brightness(a, pedestal)
    return float(ratio ** (1 / (b.time - a.time)))


def sky_ahead(exposure: float, next_exposure: float) -> float:
    return exposure / 2 + OVERHEAD + next_exposure / 2


# -- the service ---------------------------------------------------------------------


class Capture(Protocol):
    def camera(self, role: Role) -> object: ...
    async def configure(
        self, role: Role, settings: CameraSettings, *, job: str | None = None
    ) -> None: ...
    async def take(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        label: str = "",
    ) -> Shot: ...
    async def level(self, shot: Shot) -> float: ...
    async def keep(
        self, context: JobContext, role: Role, shot: Shot, label: str = ""
    ) -> Captured: ...


class Filters(Protocol):
    async def select_in(self, context: JobContext, filter: int | str) -> Json: ...


class Focuser(Protocol):
    async def move_to(self, position: int) -> None: ...


class Mount(Protocol):
    async def slew(
        self, context: JobContext, ra: float, dec: float, *, force: bool = False
    ) -> Coordinates: ...
    async def set_tracking(
        self, on: bool | None, mode: str | None = None, *, job: str | None = None
    ) -> None: ...


class Levels(Protocol):
    def set_level(self, frame_id: int, level: float | None) -> None: ...


@dataclass(slots=True)
class _Progress:
    filter: str | None
    count: int
    done: int = 0
    exposure: float | None = None
    level: float | None = None
    state: Literal["pending", "running", "done", "ended", "failed", "cancelled"] = "pending"
    message: str | None = None
    samples: list[Sample] = field(default_factory=list[Sample])

    def summary(self) -> dict[str, Json]:
        return {
            "filter": self.filter,
            "count": self.count,
            "done": self.done,
            "exposure": round(self.exposure, 4) if self.exposure is not None else None,
            "level": round(self.level) if self.level is not None else None,
            "state": self.state,
            "message": self.message,
        }


class FlatsService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        capture: Capture,
        filters: Callable[[], Filters | None],
        focuser: Callable[[], Focuser | None],
        levels: Levels,
        clock: Callable[[], float] = time.monotonic,
        *,
        site: Callable[[], Location | None] = lambda: None,
        mount: Callable[[], Mount | None] = lambda: None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._capture = capture
        self._filters = filters
        self._focuser = focuser
        self._levels = levels
        self._clock = clock
        self._site = site
        self._mount = mount
        self._now = now
        self._sleep = sleep
        self._message: str | None = None
        self._published: dict[str, Json] | None = None
        store.set(ROOT, None)

    def windows(self) -> tuple[float, list[twilight.Window]]:
        """The Sun's altitude now and the twilight windows of the next day."""
        site = self._site()
        if site is None:
            raise FlatsError("sky flats need the site: set it in the profile")
        now = self._now()
        return twilight.sun(site, now)[0], twilight.windows(site, now)

    def resources(self, plan: FlatPlan) -> list[str]:
        roles = [Role.MAIN_CAMERA, Role.FILTER_WHEEL, Role.FOCUSER]
        if plan.source == "sky":
            roles.append(Role.MOUNT)
        return [role.value for role in roles]

    def start(self, plan: FlatPlan) -> str:
        """The wizard as a job of its own; returns its id."""

        self._capture.camera(CAMERA)  # refused now, not in the job, when not connected

        async def run(context: JobContext) -> Json:
            return await self.run(context, plan)

        return self._jobs.start("flats", self.resources(plan), run)

    async def run(self, context: JobContext, plan: FlatPlan) -> dict[str, Json]:
        """Take the plan's flats inside ``context``'s job; what each filter got."""
        wanted = list(plan.filters)
        progress = [_Progress(f.filter, f.count) for f in wanted]
        self._message = None
        self._publish(plan, progress, "running", None)
        outcome: Literal["succeeded", "failed", "cancelled"] = "failed"
        error: str | None = None
        try:
            phase: twilight.Phase | None = None
            if plan.source == "sky":
                phase = await self._open_sky(context, plan, progress)
                names = [f.filter for f in wanted]
                wanted = twilight.ordered(wanted, names, phase)
                progress[:] = twilight.ordered(list(progress), names, phase)
            await self._configure(context, plan)
            pedestal = await self._pedestal(context, plan.min_exposure)
            log.info("flats: pedestal %.0f ADU", pedestal)
            exposure = plan.start_exposure or (1.0 if plan.source == "panel" else 0.5)
            for filter, state in zip(wanted, progress, strict=True):
                exposure = await self._filter(
                    context, plan, filter, state, pedestal, exposure, progress, phase
                )
            failed = [p for p in progress if p.state == "failed"]
            outcome = "failed" if len(failed) == len(progress) else "succeeded"
            if failed:
                error = "; ".join(f"{p.filter or 'no filter'}: {p.message}" for p in failed)
        except asyncio.CancelledError:
            outcome = "cancelled"
            for p in progress:
                if p.state in ("pending", "running"):
                    p.state = "cancelled"
            raise
        except Exception as e:
            error = str(e) or type(e).__name__
            for p in progress:
                if p.state in ("pending", "running"):
                    p.state, p.message = "failed", error
            raise
        finally:
            self._message = None
            self._publish(plan, progress, outcome, error)
        if outcome == "failed":
            raise FlatsError(error or "no flats were taken")
        return {"filters": [p.summary() for p in progress]}

    async def _open_sky(
        self, context: JobContext, plan: FlatPlan, progress: list[_Progress]
    ) -> twilight.Phase:
        """Wait for the twilight window, then point high up opposite the Sun, not tracking."""
        site = self._site()
        if site is None:
            raise FlatsError("sky flats need the site: set it in the profile")
        mount = self._mount()
        if mount is None:
            raise FlatsError("sky flats need the mount")
        phase = twilight.phase(site, self._now())
        while True:
            altitude, _ = twilight.sun(site, self._now())
            if twilight.SUN_LOW <= altitude <= twilight.SUN_HIGH:
                break
            if (phase == "dusk") == (altitude < twilight.SUN_LOW):
                raise FlatsError(f"the {phase} twilight is over: the Sun is at {altitude:.0f}°")
            edge = twilight.SUN_HIGH if phase == "dusk" else twilight.SUN_LOW
            self._message = f"waiting for the Sun to reach {edge:g}° (now {altitude:.1f}°)"
            context.progress(None, self._message)
            self._publish(plan, progress, "running", None)
            await self._sleep(SKY_WAIT)
        spot = twilight.flat_spot(site, self._now())
        self._message = "pointing opposite the Sun"
        self._publish(plan, progress, "running", None)
        await mount.slew(context, spot.ra, spot.dec)
        await mount.set_tracking(False, job=context.id)
        self._message = None
        return phase

    def _sky_open(self, phase: twilight.Phase) -> bool:
        site = self._site()
        if site is None:
            return False
        altitude, _ = twilight.sun(site, self._now())
        return altitude >= twilight.SUN_LOW if phase == "dusk" else altitude <= twilight.SUN_HIGH

    async def _configure(self, context: JobContext, plan: FlatPlan) -> None:
        settings = CameraSettings(gain=plan.gain, offset=plan.offset, binning=plan.binning)
        if settings != CameraSettings():
            await self._capture.configure(CAMERA, settings, job=context.id)

    async def _pedestal(self, context: JobContext, exposure: float) -> float:
        """The level of a frame with (almost) no light: the camera's offset."""
        shot = await self._capture.take(context, CAMERA, exposure, FrameType.BIAS, "pedestal: ")
        try:
            return await self._capture.level(shot)
        finally:
            shot.path.unlink(missing_ok=True)

    async def _filter(
        self,
        context: JobContext,
        plan: FlatPlan,
        wanted: FlatFilter,
        progress: _Progress,
        pedestal: float,
        exposure: float,
        everything: list[_Progress],
        phase: twilight.Phase | None,
    ) -> float:
        """Take one filter's flats; the exposure it ended with, the next filter's start."""
        progress.state = "running"
        self._publish(plan, everything, "running", None)
        name = wanted.filter or "flat"
        if wanted.filter is not None:
            filters = self._filters()
            if filters is None:
                raise FlatsError(f"no filter wheel to select {wanted.filter}")
            await filters.select_in(context, wanted.filter)
        if wanted.focus is not None and (focuser := self._focuser()) is not None:
            context.progress(None, f"{name}: focuser to {wanted.focus}")
            await focuser.move_to(wanted.focus)

        target = plan.target
        band = plan.tolerance * (1 if plan.source == "panel" else 2) * FULL_SCALE
        misses = 0
        while progress.done < progress.count:
            exposure = min(max(exposure, plan.min_exposure), plan.max_exposure)
            progress.exposure = exposure
            label = f"{name} {progress.done + 1}/{progress.count}: "
            started = self._clock()
            shot = await self._capture.take(context, CAMERA, exposure, FrameType.FLAT, label)
            sample = Sample(exposure, 0, started + exposure / 2)
            try:
                level = await self._capture.level(shot)
            except BaseException:
                shot.path.unlink(missing_ok=True)
                raise
            sample = Sample(exposure, level, sample.time)
            progress.level = level
            if abs(level - target) <= band:
                captured = await self._capture.keep(context, CAMERA, shot, label)
                frame = captured.result.get("id")
                if isinstance(frame, int):
                    self._levels.set_level(frame, round(level, 1))
                progress.done += 1
                progress.samples.append(sample)
                misses = 0
            else:
                shot.path.unlink(missing_ok=True)
                misses += 1
                log.info("flats: %s at %.3g s is %.0f ADU, not %.0f", name, exposure, level, target)
            trend = trend_of(progress.samples, pedestal) if plan.source == "sky" else 1.0
            wanted_next = next_exposure(sample, pedestal, target, trend=trend)
            if plan.source == "sky":
                wanted_next = next_exposure(
                    sample, pedestal, target, trend=trend, ahead=sky_ahead(exposure, wanted_next)
                )
            self._publish(plan, everything, "running", None)
            if problem := _out_of_reach(plan, exposure, level, target, band, wanted_next):
                if phase is not None and _time_helps(phase, wanted_next, exposure):
                    if not self._sky_open(phase):
                        progress.state, progress.message = "failed", f"the {phase} twilight is over"
                        self._publish(plan, everything, "running", None)
                        return exposure
                    self._message = f"{name}: {problem}; waiting"
                    context.progress(None, self._message)
                    self._publish(plan, everything, "running", None)
                    await self._sleep(SKY_WAIT)
                    self._message = None
                    exposure = wanted_next
                    continue
                if plan.source == "sky" and progress.done:
                    progress.state, progress.message = "ended", problem
                    self._publish(plan, everything, "running", None)
                    return wanted_next
                progress.state, progress.message = "failed", problem
                self._publish(plan, everything, "running", None)
                return exposure
            if misses >= MAX_MISSES:
                progress.state = "failed"
                progress.message = f"no exposure gave {plan.level:.0%} after {misses} tries"
                self._publish(plan, everything, "running", None)
                return exposure
            exposure = wanted_next
        progress.state = "done"
        self._publish(plan, everything, "running", None)
        return exposure

    def _publish(
        self, plan: FlatPlan, progress: list[_Progress], state: str, error: str | None
    ) -> None:
        summary: dict[str, Json] = {
            "source": plan.source,
            "state": state,
            "target": round(plan.target),
            "tolerance": plan.tolerance,
            "filters": [p.summary() for p in progress],
            "message": self._message,
            "error": error,
        }
        if summary != self._published:
            self._store.set(ROOT, summary)
            self._published = summary


def _time_helps(phase: twilight.Phase, wanted: float, exposure: float) -> bool:
    """Whether waiting brings the exposure within reach: a sky too bright at dusk (it
    wants a shorter one), too dark at dawn (a longer one)."""
    return wanted < exposure if phase == "dusk" else wanted > exposure


def _out_of_reach(
    plan: FlatPlan, exposure: float, level: float, target: float, band: float, wanted: float
) -> str | None:
    """Why the level cannot be reached within the exposure limits, if it cannot."""
    sky = plan.source == "sky"
    if level < target - band and exposure >= plan.max_exposure and wanted > plan.max_exposure:
        return (
            "the sky is too dark now"
            if sky
            else (f"too dim at {plan.max_exposure:g} s: brighten the panel or raise the gain")
        )
    if level > target + band and exposure <= plan.min_exposure and wanted < plan.min_exposure:
        return (
            "the sky is too bright still"
            if sky
            else (f"too bright at {plan.min_exposure:g} s: dim the panel or add a diffuser")
        )
    if (
        sky
        and (wanted > plan.max_exposure or wanted < plan.min_exposure)
        and not math.isnan(wanted)
    ):
        return (
            "the sky is too dark now" if wanted > plan.max_exposure else "the sky is too bright now"
        )
    return None
