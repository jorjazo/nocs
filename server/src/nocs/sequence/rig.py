"""The rig behind a running sequence: each step through a service's in-job function.

Everything happens inside the sequence's job, which holds the main camera, the
filter wheel, the focuser and the mount (ADR 0031). Cooling and power outputs
take no lock. Guiding runs under the job's hold of the mount, so the sequence
stops it before every slew and park.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass
from typing import Protocol

import anyio

from nocs.devices import Coordinates, DeviceError, FrameType
from nocs.devices.camera import SensorInfo
from nocs.equipment import Role
from nocs.filters.service import FilterWheelNotReadyError
from nocs.focus.autofocus import AutofocusError, AutofocusOptions
from nocs.focus.service import FocuserNotReadyError
from nocs.focus.sweep import Problem
from nocs.guiding import GuidingError, GuidingNotReadyError, Phd2ConnectionError, Phd2Error
from nocs.imaging.capture import FRAME_TYPES, CameraNotReadyError, CameraSettings, Captured
from nocs.jobs import JobContext, JobManager
from nocs.mount.service import MountNotReadyError, PointingError
from nocs.pointing import CenteringError
from nocs.sequence.model import (
    Action,
    Autofocus,
    Cool,
    ExposurePlan,
    Guide,
    Outputs,
    Park,
    PlanRow,
    SelectFilter,
    Slew,
    Target,
    Unpark,
    Warm,
)
from nocs.sequence.runner import FrameResult, StepError
from nocs.solving import SolveError
from nocs.state import Json, StateStore
from nocs.storage import StorageError
from nocs.storage.environment import number

log = logging.getLogger(__name__)

CAMERA = Role.MAIN_CAMERA
FOCUS_FACTS = ("position", "hfr", "start_position", "start_hfr", "temperature", "filter")
"""What a sequence's events keep of an autofocus run."""
COOLING_TOLERANCE = 1.0
"""°C from the target that count as there."""
WARM_TOLERANCE = 2.0
WARM_TARGET = 15.0
"""°C to warm to before switching the cooler off, when the ambient is unknown."""
DEFAULT_RAMP = 3.0
"""°C per minute assumed to estimate how long cooling may take."""
COOLING_MARGIN = 600.0
"""Seconds of patience beyond that estimate."""
POLL = 5.0


class CameraDevice(Protocol):
    @property
    def can_cool(self) -> bool: ...
    @property
    def sensor(self) -> SensorInfo: ...
    @property
    def temperature(self) -> float | None: ...
    @property
    def gain(self) -> float | None: ...
    @property
    def offset(self) -> float | None: ...
    @property
    def binning(self) -> tuple[int, int]: ...


class Capture(Protocol):
    def camera(self, role: Role) -> CameraDevice: ...
    async def configure(
        self, role: Role, settings: CameraSettings, *, job: str | None = None
    ) -> None: ...
    async def set_cooling(
        self, role: Role, on: bool, target: float | None = None, ramp: float | None = None
    ) -> None: ...
    async def capture(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        *,
        save: bool,
        target: str | None = None,
    ) -> Captured: ...


class Filters(Protocol):
    async def select_in(self, context: JobContext, filter: int | str) -> Json: ...


class Focus(Protocol):
    def options(self) -> AutofocusOptions: ...
    async def run(self, context: JobContext, options: AutofocusOptions) -> dict[str, Json]: ...


class MountControl(Protocol):
    async def unpark(self, *, job: str | None = None) -> None: ...
    async def park_in(self, context: JobContext) -> None: ...
    async def set_tracking(
        self, on: bool | None, mode: str | None = None, *, job: str | None = None
    ) -> None: ...
    async def slew(
        self, context: JobContext, ra: float, dec: float, *, force: bool = False
    ) -> Coordinates: ...


class Guiding(Protocol):
    @property
    def guiding(self) -> bool: ...
    async def start(self, context: JobContext) -> Json: ...
    async def stop(self) -> None: ...
    def guide_under(self, job_id: str | None) -> None: ...


class Power(Protocol):
    async def set_output(
        self, output_id: str, *, on: bool | None = None, job: str | None = None
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class Parts:
    """The services a sequence drives; ``None`` for what the rig lacks."""

    capture: Capture
    filters: Filters | None
    focus: Focus | None
    mount: MountControl | None
    guiding: Guiding | None
    power: Power | None


def take_back(jobs: JobManager, job: str, guiding: Guiding | None) -> None:
    """Take a paused sequence's devices back; ``ResourceBusyError`` while one is in use."""
    if guiding is not None:
        guiding.guide_under(job)  # PHD2 guides under the sequence's hold of the mount again
    jobs.resume(job)


@contextlib.contextmanager
def _classified() -> Generator[None]:
    """Turn the rig's failures into the kinds the recovery policies know (ADR 0032)."""
    try:
        yield
    except StepError:
        raise
    except AutofocusError as e:
        clouds = e.problem in (Problem.NO_STARS, Problem.TOO_FEW_STARS)
        raise StepError("clouds" if clouds else "focus", f"autofocus: {e}") from e
    except (GuidingError, GuidingNotReadyError, Phd2Error, Phd2ConnectionError) as e:
        raise StepError("guiding", str(e) or type(e).__name__) from e
    except (SolveError, CenteringError) as e:
        raise StepError("solve", str(e) or type(e).__name__) from e
    except StorageError as e:
        raise StepError("storage", str(e) or type(e).__name__) from e
    except (
        DeviceError,
        TimeoutError,
        ConnectionError,
        CameraNotReadyError,
        FilterWheelNotReadyError,
        FocuserNotReadyError,
        MountNotReadyError,
        PointingError,
    ) as e:
        raise StepError("device", str(e) or type(e).__name__) from e


class RigExecutor:
    def __init__(
        self,
        context: JobContext,
        jobs: JobManager,
        store: StateStore,
        parts: Parts,
        *,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        self._context = context
        self._jobs = jobs
        self._store = store
        self._parts = parts
        self._sleep = sleep
        self._guided = False
        """The sequence asked for guiding: frames are taken guided."""

    async def action(self, action: Action, target: Target | None) -> dict[str, Json] | None:
        with _classified():
            return await self._action(action, target)

    async def frame(self, plan: ExposurePlan, row: PlanRow, target: Target | None) -> FrameResult:
        with _classified():
            await self._keep_guiding()
            return await self._frame(plan, row, target)

    async def _action(self, action: Action, target: Target | None) -> dict[str, Json] | None:
        context, parts = self._context, self._parts
        match action:
            case Cool():
                await parts.capture.set_cooling(CAMERA, True, action.temperature, action.ramp)
                if action.wait:
                    await self._reach(action.temperature, COOLING_TOLERANCE, action.ramp)
                return {"temperature": parts.capture.camera(CAMERA).temperature}
            case Warm():
                await self._warm(action.ramp)
            case Unpark():
                await self._mount().unpark(job=context.id)
            case Park():
                await self._stop_guiding()
                mount = self._mount()
                try:
                    await mount.park_in(context)
                except DeviceError as e:  # it cannot park: at least stop it moving
                    log.info("not parking: %s; switching tracking off", e)
                    await mount.set_tracking(False, job=context.id)
            case Slew():
                if target is None or target.ra is None or target.dec is None:
                    raise ValueError("a slew needs a target with coordinates")
                await self._stop_guiding()
                await self._mount().slew(context, target.ra, target.dec)
            case SelectFilter():
                if parts.filters is None:
                    raise ValueError("the rig has no filter wheel")
                await parts.filters.select_in(context, action.filter)
            case Autofocus():
                if parts.focus is None:
                    raise ValueError("the rig has no focuser")
                run = await parts.focus.run(context, parts.focus.options())
                return {k: run.get(k) for k in FOCUS_FACTS}
            case Guide():
                if parts.guiding is None:
                    raise ValueError("the rig has no guiding")
                self._guided = action.on
                if action.on:
                    await parts.guiding.start(context)
                else:
                    await parts.guiding.stop()
            case Outputs():
                if parts.power is None:
                    raise ValueError("the rig has no power box")
                for output in action.outputs:
                    await parts.power.set_output(output, on=action.on, job=context.id)

    async def _frame(self, plan: ExposurePlan, row: PlanRow, target: Target | None) -> FrameResult:
        capture = self._parts.capture
        camera = capture.camera(CAMERA)
        settings = CameraSettings(
            gain=row.gain if row.gain is not None and row.gain != camera.gain else None,
            offset=row.offset if row.offset is not None and row.offset != camera.offset else None,
            binning=row.binning
            if row.binning is not None and row.binning != camera.binning[0]
            else None,
        )
        if settings != CameraSettings():
            await capture.configure(CAMERA, settings, job=self._context.id)
        captured = await capture.capture(
            self._context,
            CAMERA,
            row.exposure,
            FRAME_TYPES[plan.frame_type],
            save=True,
            target=target.name if target is not None and plan.frame_type == "light" else None,
        )
        guiding = captured.result.get("guiding")
        if self._guided and isinstance(guiding, dict) and (lost := guiding.get("lost")):
            raise StepError("guiding", f"the guide star was lost {lost} times during the frame")
        frame = captured.result.get("id")
        return FrameResult(
            stars=captured.stars, hfr=captured.hfr, frame=frame if isinstance(frame, int) else None
        )

    async def _keep_guiding(self) -> None:
        """Guide again before a frame when the sequence guides and PHD2 does not (any more)."""
        guiding = self._parts.guiding
        if not self._guided or guiding is None:
            return
        if self._store.get(("guiding", "app_state")) == "Guiding":
            return
        if guiding.guiding:  # lost its star, or still calibrating
            await guiding.stop()
        self._context.progress(None, "guiding again")
        await guiding.start(self._context)

    async def paused(self) -> None:
        self._jobs.suspend(self._context.id)
        if self._parts.guiding is not None:
            self._parts.guiding.guide_under(None)  # NOCS holds the mount for PHD2 meanwhile

    async def resumed(self) -> None:
        take_back(self._jobs, self._context.id, self._parts.guiding)

    def focuser_temperature(self) -> float | None:
        return number(self._store, ("focuser", "temperature"))

    # -- internals --------------------------------------------------------------------

    def _mount(self) -> MountControl:
        if self._parts.mount is None:
            raise ValueError("the rig has no mount")
        return self._parts.mount

    async def _stop_guiding(self) -> None:
        guiding = self._parts.guiding
        if guiding is not None and guiding.guiding:
            await guiding.stop()

    async def _reach(self, target: float, tolerance: float, ramp: float | None) -> None:
        """Wait until the sensor is within ``tolerance`` of ``target``, or give up and go on."""
        camera = self._parts.capture.camera(CAMERA)
        start = camera.temperature
        if start is None:
            return
        patience = abs(start - target) / (ramp or DEFAULT_RAMP) * 60 + COOLING_MARGIN
        waited = 0.0
        while (now := camera.temperature) is not None and abs(now - target) > tolerance:
            if waited >= patience:
                log.warning(
                    "the camera is at %.1f °C after %.0f s, not %.1f °C: going on",
                    now,
                    waited,
                    target,
                )
                return
            self._context.progress(None, f"sensor at {now:.1f} °C, going to {target:g} °C")
            await self._sleep(POLL)
            waited += POLL

    async def _warm(self, ramp: float | None) -> None:
        """Bring the sensor up to the ambient with the ramp, then switch the cooler off."""
        capture = self._parts.capture
        camera = capture.camera(CAMERA)
        if not camera.can_cool:
            return
        ambient = number(self._store, ("weather", "temperature"))
        target = ambient if ambient is not None else WARM_TARGET
        now = camera.temperature
        if now is not None and now < target - WARM_TOLERANCE:
            await capture.set_cooling(CAMERA, True, target, ramp)
            await self._reach(target, WARM_TOLERANCE, ramp)
        await capture.set_cooling(CAMERA, False)
