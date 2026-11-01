"""PHD2 for the active profile: the connection to it, its settings, and its state (ADR 0022).

State layout under ``("guiding",)``::

    phd2:      {host, port, connected, version, error}
    managed:   whether nocsd writes PHD2's settings (NOCS_PHD2_SETTINGS)
    settings:  none | pending | applying | applied | failed | user
    profile:   the PHD2 profile in use, by name
    app_state: PHD2's own state (Stopped, Selected, Looping, Calibrating, Guiding,
               LostLock, Paused), or None while unknown
    equipment: PHD2 is connected to the guide camera and the mount
    exposure:  PHD2's exposure, seconds, or None while unknown
    calibration: {ra_angle, ra_rate, dec_angle, dec_rate, declination}, or None
    calibrating: {direction, step, distance}: PHD2's latest calibration step while it
               calibrates, or None
    settling:  PHD2 waits for the star to settle (after starting to guide or a dither)
    alert:     {message, kind, time}: the last thing PHD2 warned about, or None
    pixel_scale: of the guide camera as PHD2 has it, arcseconds per pixel, or None
    stats:     the guiding RMS (``nocs.guiding.stats``) and the last guide step, or None
    error:     why PHD2 does not run the profile's settings, or None

When nocsd manages the settings, it renders them from the active profile once its
guide camera and mount are ready. If PHD2 runs another profile, nocsd writes the
file and asks PHD2 to shut down; PHD2's service imports the file as it starts
again. That never happens while PHD2 is busy or connected to its equipment: the
change waits until it stops.

While PHD2's equipment is connected, the guide camera is PHD2's: NOCS holds the
role with a reservation, refuses its own exposures, and shows PHD2's frames as
previews (ADR 0023). While PHD2 calibrates or guides, NOCS also holds the mount, so
that slews, parking and the pad wait until guiding stops.

Starting to guide is a job: loop, select a star, calibrate if needed, guide, and
wait until PHD2 has settled. Guiding goes on after the job ends, until ``stop``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path as FsPath
from typing import Any, Protocol

import anyio

from nocs.devices import Camera, DeviceError, Mount
from nocs.equipment import EquipmentService, Role
from nocs.equipment.profiles import write_atomic
from nocs.equipment.service import IndiConnection
from nocs.guiding.phd2 import (
    Phd2Client,
    Phd2Closed,
    Phd2ConnectionError,
    Phd2Error,
    Phd2Event,
    Phd2Message,
)
from nocs.guiding.settings import GuideRig, Phd2Settings, render
from nocs.guiding.stats import GuideEntry, GuideHistory, rms
from nocs.indi import IndiClient
from nocs.jobs import JobContext, JobManager, ResourceBusyError
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("guiding",)
_BACKOFF = (1.0, 2.0, 5.0, 10.0)
RESTART_BACKOFF = 1.0
"""How soon to look for PHD2 again after asking it to restart…"""
RESTART_ATTEMPTS = 20
"""…and for how many attempts, before the usual backoff."""

IDLE_STATES = frozenset({"Stopped"})
"""PHD2 states in which it does not expose. "Selected" is not one: PHD2 2.6.14 reports it
while looping with a star selected, although its documentation says otherwise."""
LOOPING_STATES = frozenset({"Looping", "Selected"})
CAMERA = Role.GUIDE_CAMERA
HOLDER = "phd2"
CONNECT_TIMEOUT = 60.0
STOP_MARGIN = 15.0
LOOP_STOPPED = 2.0
"""How long after guiding stopped PHD2 may take to tell that its loop stopped too."""
SETTLE_MARGIN = 30.0
"""Beyond PHD2's own settle timeout, before NOCS stops waiting for its answer."""
MAX_DITHER = 50.0
"""Guide pixels."""
CAPTURE_ENDING = 10.0
"""How long PHD2 may refuse to (dis)connect because a capture is still ending."""
"""How long the exposure PHD2 was taking may run over when it stops."""
EXPOSURE_RANGE = (0.05, 60.0)
GUIDING_STATES = frozenset({"Calibrating", "Guiding", "LostLock"})
"""PHD2 states in which it moves the mount: NOCS holds the mount meanwhile."""
FIND_STAR_ATTEMPTS = 5
"""Frames to try ``find_star`` on before giving up."""
FIRST_FRAME_MARGIN = 20.0
STAR_EDGE = 0.1
"""Guide stars are picked away from the frame's edges (this fraction, at least 50 px):
calibration moves the star by 25 px each way, and a star near the edge is lost."""
LOST_WHILE_CALIBRATING = 30.0
"""Seconds (or 10 exposures, if longer) without the star before calibration is given up.
PHD2 counts no step while the star is lost, so it would calibrate forever."""

_STATE_OF_EVENT = {
    "LoopingExposures": "Looping",
    "LoopingExposuresStopped": "Stopped",
    "StartCalibration": "Calibrating",
    "Calibrating": "Calibrating",
    "StartGuiding": "Guiding",
    "GuideStep": "Guiding",
    "GuidingStopped": "Stopped",
    "Paused": "Paused",
}
"""Events that tell PHD2's state unambiguously."""

_QUERY_EVENTS = frozenset({"Resumed", "StarSelected", "CalibrationComplete", "CalibrationFailed"})
"""Events after which PHD2's state is asked for."""


class SettingsStatus(StrEnum):
    NONE = "none"
    """Nothing to apply: no profile connected, or its guide camera or mount not ready."""
    PENDING = "pending"
    """Waiting for PHD2 to be reachable and stopped."""
    APPLYING = "applying"
    """PHD2 was asked to restart with new settings."""
    APPLIED = "applied"
    FAILED = "failed"
    USER = "user"
    """nocsd does not manage PHD2's settings."""


class GuidingNotReadyError(Exception):
    """PHD2 cannot do that now: unreachable, other settings, or devices missing."""


class GuidingError(Exception):
    """Guiding did not start: no star, calibration failed, PHD2 stopped, no settle."""


@dataclass(frozen=True, slots=True)
class Settle:
    """When PHD2 counts as settled: within ``pixels`` for ``time`` s, giving up at ``timeout``."""

    pixels: float = 1.5
    time: float = 10.0
    timeout: float = 60.0

    def params(self) -> dict[str, Json]:
        return {"pixels": self.pixels, "time": self.time, "timeout": self.timeout}


class FrameFollower(Protocol):
    """Shows the frames PHD2 takes (``CaptureService``)."""

    def follow(self, role: Role, by: str, exposure: Callable[[], float]) -> None: ...

    def unfollow(self, role: Role) -> None: ...


class GuidingService:
    def __init__(
        self,
        store: StateStore,
        equipment: EquipmentService,
        bridge: IndiConnection,
        jobs: JobManager,
        frames: FrameFollower | None = None,
        *,
        host: str,
        port: int,
        settings_file: FsPath | None,
        indi_host: str,
        indi_port: int,
    ) -> None:
        self._store = store
        self._equipment = equipment
        self._jobs = jobs
        self._frames = frames
        self._hold: str | None = None
        """The reservation of the guide camera while PHD2's equipment is connected."""
        self._exposure: float | None = None
        self._idle = asyncio.Event()
        self._commands = asyncio.Lock()
        self._mount_hold: str | None = None
        """The reservation of the mount while PHD2 calibrates or guides."""
        self._starting: str | None = None
        """The job starting to guide, while it runs."""
        self._under: str | None = None
        """The job guiding goes on under, which holds the mount itself (a sequence)."""
        self._queues: set[asyncio.Queue[Phd2Message]] = set()
        self._history = GuideHistory()
        self._settling = False
        self._pixel_scale: float | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._host = host
        self._port = port
        self._settings_file = settings_file
        self._indi_host = indi_host
        self._indi_port = indi_port
        self._indi: IndiClient | None = bridge.client
        self._phd2: Phd2Client | None = None
        self._app_state: str | None = None
        self._desired: Phd2Settings | None = None
        self._desired_error: str | None = None
        self._attempted: str | None = None
        """Name of the settings PHD2 was last restarted for."""
        self._changed = asyncio.Event()

        store.set(
            ROOT,
            {
                "phd2": self._server(connected=False),
                "managed": settings_file is not None,
                "settings": (SettingsStatus.NONE if settings_file else SettingsStatus.USER).value,
                "profile": None,
                "app_state": None,
                "equipment": False,
                "exposure": None,
                "calibration": None,
                "calibrating": None,
                "settling": False,
                "alert": None,
                "pixel_scale": None,
                "stats": None,
                "error": None,
            },
        )
        self._unwatch_bridge = bridge.watch(self._on_indi)
        self._unwatch_equipment = equipment.add_listener(self._refresh)
        self._refresh()

    @property
    def managed(self) -> bool:
        return self._settings_file is not None

    @property
    def settings(self) -> Phd2Settings | None:
        """What PHD2 should run for the active profile, when nocsd manages it."""
        return self._desired

    @property
    def phd2(self) -> Phd2Client | None:
        """The connected PHD2, if any."""
        return self._phd2 if self._phd2 is not None and self._phd2.connected else None

    @property
    def equipment_connected(self) -> bool:
        return self._hold is not None

    @property
    def history(self) -> GuideHistory:
        """The guide steps of the current guiding run."""
        return self._history

    @property
    def pixel_scale(self) -> float | None:
        return self._pixel_scale

    @property
    def guiding(self) -> bool:
        """PHD2 calibrates or guides, or a start of guiding runs.

        NOCS holds the mount meanwhile, unless a job that started guiding holds it.
        """
        return self._starting is not None or self._app_state in GUIDING_STATES

    async def connect(self) -> None:
        """Connect PHD2 to the guide camera and the mount; the camera is PHD2's then."""
        async with self._commands:
            await self._connect()

    async def loop(self, exposure: float | None = None) -> None:
        """Expose with PHD2 again and again (connecting it first), without guiding."""
        async with self._commands:
            client = await self._connect()
            if exposure is not None:
                await self._set_exposure(client, exposure)
            await client.call("loop")

    async def set_exposure(self, exposure: float) -> None:
        async with self._commands:
            await self._set_exposure(self._client(), exposure)

    async def stop(self) -> None:
        """Stop PHD2's looping or guiding, and wait until its exposure ends."""
        if self._starting is not None:
            self._jobs.cancel(self._starting)
        async with self._commands:
            await self._stop(self._client())

    def guide(self, *, recalibrate: bool = False, settle: Settle | None = None) -> str:
        """Start guiding as a job that ends once PHD2 has settled; returns the job id.

        PHD2 calibrates first when it has no calibration, or when ``recalibrate`` asks
        for it (after rotating a camera that guides through the imaging optics).
        Guiding goes on after the job, until ``stop``.
        """
        self._client()  # fail now, not in the job, when PHD2 is not there
        settle = _checked(settle)

        async def run(context: JobContext) -> Json:
            return await self.start(context, recalibrate=recalibrate, settle=settle)

        return self._jobs.start("guide", [HOLDER], run)

    async def start(
        self, context: JobContext, *, recalibrate: bool = False, settle: Settle | None = None
    ) -> Json:
        """Start guiding inside ``context``'s job (the sequencer's, or ``guide``'s).

        When that job holds the mount itself, NOCS does not reserve it for guiding
        meanwhile: the job must stop guiding before it moves the mount.
        """
        settle = _checked(settle)
        if self._jobs.holder(Role.MOUNT.value) == context.id:
            self.guide_under(context.id)
        self._starting = context.id
        try:
            return await self._start_guiding(context, recalibrate, settle)
        finally:
            self._starting = None
            self._sync_mount_hold()

    def guide_under(self, job_id: str | None) -> None:
        """Guiding goes on under ``job_id``'s job, which holds the mount itself.

        NOCS lets go of its own hold on the mount at once, and takes it again only
        once that job has finished (or after ``guide_under(None)``). A sequence calls
        it before resuming (``JobManager.resume``) to get the mount back, and with
        None after suspending, so that NOCS keeps the mount while it is paused.
        ``start`` inside a job that holds the mount does it by itself.
        """
        self._under = job_id
        if job_id is not None and self._mount_hold is not None:
            self._jobs.release(self._mount_hold)
            self._mount_hold = None
        self._sync_mount_hold()

    def dither_job(
        self, pixels: float, *, settle: Settle | None = None, ra_only: bool = False
    ) -> str:
        """Dither by up to ``pixels`` of the guide camera as a job of its own; returns its id."""
        self._client()
        settle = _checked(settle)

        async def run(context: JobContext) -> Json:
            return await self.dither(context, pixels, settle=settle, ra_only=ra_only)

        return self._jobs.start("dither", [HOLDER], run)

    async def dither(
        self,
        context: JobContext,
        pixels: float,
        *,
        settle: Settle | None = None,
        ra_only: bool = False,
    ) -> Json:
        """Move the lock position by up to ``pixels`` guide pixels and wait until settled.

        Runs inside ``context``'s job (a series of frames, the sequencer). Raises
        ``GuidingError`` when PHD2 does not settle in time; it goes on guiding.
        """
        settle = _checked(settle)
        if not 0 < pixels <= MAX_DITHER:
            raise ValueError(f"a dither must be 0..{MAX_DITHER:g} guide pixels")
        client = self._client()
        if self._app_state != "Guiding":
            raise GuidingNotReadyError(f"PHD2 is not guiding ({self._app_state or 'unknown'})")
        queue: asyncio.Queue[Phd2Message] = asyncio.Queue()
        self._queues.add(queue)
        try:
            context.progress(None, f"dithering {pixels:.1f} px")
            params: dict[str, Json] = {
                "amount": pixels,
                "raOnly": ra_only,
                "settle": settle.params(),
            }
            await client.call("dither", params)
            async with asyncio.timeout(settle.timeout + SETTLE_MARGIN):
                while True:
                    message = await queue.get()
                    if isinstance(message, Phd2Closed):
                        raise Phd2ConnectionError(f"lost PHD2 while dithering: {message.reason}")
                    match message.name:
                        case "Settling":
                            distance = message.data.get("Distance")
                            if isinstance(distance, int | float):
                                context.progress(
                                    None, f"settling after the dither: {distance:.1f} px"
                                )
                        case "SettleDone":
                            if message.data.get("Status") != 0:
                                reason = message.data.get("Error") or "timed out"
                                raise GuidingError(
                                    f"PHD2 did not settle after the dither ({reason})"
                                )
                            return {"pixels": pixels, "frames": message.data.get("TotalFrames")}
                        case "GuidingStopped":
                            raise GuidingError("PHD2 stopped guiding while dithering")
                        case _:
                            pass
        finally:
            self._queues.discard(queue)

    def guide_pixels(self, main_pixels: float) -> float:
        """Main camera pixels as guide camera pixels, from both trains' pixel scales."""
        main = self._store.get(("cameras", Role.MAIN_CAMERA.value, "field", "scale"))
        if not isinstance(main, int | float) or isinstance(main, bool) or main <= 0:
            raise GuidingNotReadyError("the main camera's pixel scale is unknown (its optics?)")
        if self._pixel_scale is None:
            raise GuidingNotReadyError("PHD2's pixel scale is unknown")
        return main_pixels * main / self._pixel_scale

    def frame_guiding(self, start: float, end: float) -> dict[str, Json] | None:
        """How guiding went from ``start`` to ``end`` (system clock, Unix seconds).

        None when PHD2 took no guide step meanwhile. PHD2 stamps its events with the
        clock of its host, which is nocsd's (or, in development, the same kernel's).
        """
        entries = self._history.between(start, end)
        result = rms(entries)
        lost = sum(1 for e in entries if e.kind == "lost")
        if result is None and lost == 0:
            return None
        if result is not None and result.count < 2:
            result = None  # one step has no spread: its "RMS" would read 0″
        scale = self._pixel_scale

        def arcsec(pixels: float | None) -> Json:
            return round(pixels * scale, 3) if pixels is not None and scale else None

        steps = sum(1 for e in entries if e.kind == "step")
        return {
            "rms_ra": arcsec(result.ra if result else None),
            "rms_dec": arcsec(result.dec if result else None),
            "rms_total": arcsec(result.total if result else None),
            "steps": steps,
            "lost": lost,
        }

    async def disconnect(self) -> None:
        """Stop PHD2, disconnect it from its equipment and give the camera back."""
        async with self._commands:
            client = self.phd2
            try:
                if client is not None:
                    await self._stop(client)
                    await self._set_connected(client, False)
            finally:
                self._release()
                self._changed.set()  # settings that waited may go in now

    async def release(self) -> None:
        """Before the equipment disconnects: free PHD2's hold, whatever happens."""
        if self._hold is None:
            return
        try:
            await self.disconnect()
        except (Phd2Error, Phd2ConnectionError, TimeoutError) as e:
            log.warning("PHD2 did not let go of its equipment cleanly: %s", e)

    async def run(self) -> None:
        """Stay connected to PHD2 until cancelled, retrying with backoff."""
        attempt = 0
        while True:
            client = Phd2Client(self._host, self._port)
            closed = False

            def on_message(message: Phd2Message) -> None:
                nonlocal closed
                if isinstance(message, Phd2Event):
                    self._on_event(message)
                else:
                    closed = True
                    self._changed.set()
                for queue in list(self._queues):
                    queue.put_nowait(message)

            client.add_listener(on_message)
            try:
                await client.connect()
            except (OSError, TimeoutError) as e:
                self._publish_server(connected=False, error=str(e) or type(e).__name__)
            else:
                attempt = 0
                self._phd2 = client
                self._publish_server(connected=True)
                log.info("connected to PHD2 at %s:%s", self._host, self._port)
                try:
                    while not closed:
                        await self._sync(client)
                        await self._changed.wait()
                        self._changed.clear()
                except Phd2ConnectionError:
                    pass
                finally:
                    self._phd2 = None
                    self._app_state = None
                    self._idle.clear()
                    self._release()  # a PHD2 that went away holds nothing
                    self._sync_mount_hold()
                    await client.close()
                    self._publish_server(connected=False)
                    with self._store.transaction():
                        self._store.set((*ROOT, "app_state"), None)
                        self._store.set((*ROOT, "profile"), None)
                        self._store.set((*ROOT, "settling"), False)
                        self._store.set((*ROOT, "calibrating"), None)
                    self._settling = False
                log.info("lost connection to PHD2")
            restarting = self._status() is SettingsStatus.APPLYING
            if restarting and attempt < RESTART_ATTEMPTS:
                delay = RESTART_BACKOFF
            else:
                delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    def close(self) -> None:
        self._unwatch_bridge()
        self._unwatch_equipment()

    # -- internals: commands ---------------------------------------------------

    def _client(self) -> Phd2Client:
        client = self.phd2
        if client is None:
            raise GuidingNotReadyError("PHD2 is not reachable")
        return client

    async def _connect(self) -> Phd2Client:
        client = self._client()
        if self._hold is not None:
            return client
        if self.managed and self._status() is not SettingsStatus.APPLIED:
            raise GuidingNotReadyError(
                self._desired_error or "PHD2 does not run the profile's settings yet"
            )
        if self._equipment.ready_device(CAMERA) is None:
            raise GuidingNotReadyError("the guide camera is not connected")
        if self._equipment.ready_device(Role.MOUNT) is None:
            raise GuidingNotReadyError("the mount is not connected")
        self._hold_camera()  # raises ResourceBusyError while NOCS uses the camera
        try:
            if await client.call("get_connected") is not True:
                await self._set_connected(client, True)
            await self._read_exposure(client)
            await self._read_calibration(client)
            await self._read_pixel_scale(client)
        except BaseException:
            self._release()
            raise
        return client

    async def _start_guiding(self, context: JobContext, recalibrate: bool, settle: Settle) -> Json:
        queue: asyncio.Queue[Phd2Message] = asyncio.Queue()
        self._queues.add(queue)
        try:
            async with self._commands:
                client = await self._connect()
            self._hold_mount()  # raises ResourceBusyError while NOCS moves the mount
            try:
                return await self._guide_steps(context, client, queue, recalibrate, settle)
            except asyncio.CancelledError:
                # Not guiding is what a cancelled start means: stop whatever began.
                with contextlib.suppress(Phd2Error, Phd2ConnectionError, TimeoutError):
                    await asyncio.shield(client.call("stop_capture"))
                raise
        finally:
            self._queues.discard(queue)

    async def _guide_steps(
        self,
        context: JobContext,
        client: Phd2Client,
        queue: asyncio.Queue[Phd2Message],
        recalibrate: bool,
        settle: Settle,
    ) -> Json:
        calibrated = False
        if self._app_state not in GUIDING_STATES:
            if self._app_state not in LOOPING_STATES:
                context.progress(None, "looping")
                await client.call("loop")
            await self._next_frame(queue)
            context.progress(None, "selecting a star")
            await self._find_star(client, queue)
        context.progress(None, "starting to guide")
        await client.call("guide", {"settle": settle.params(), "recalibrate": recalibrate})
        lost_since: float | None = None
        calibrating = False
        lost_limit = max(LOST_WHILE_CALIBRATING, 10 * (self._exposure or 1.0))
        while True:
            message = await queue.get()
            now = asyncio.get_running_loop().time()
            if calibrating and lost_since is not None and now - lost_since > lost_limit:
                with contextlib.suppress(Phd2Error, Phd2ConnectionError):
                    await client.call("stop_capture")
                raise GuidingError(
                    f"lost the guide star for {lost_limit:g} s while calibrating: stopped"
                )
            if isinstance(message, Phd2Closed):
                raise Phd2ConnectionError(f"lost PHD2 while starting to guide: {message.reason}")
            data = message.data
            match message.name:
                case "StartCalibration":
                    calibrating = True
                    context.progress(None, "calibrating")
                case "Calibrating":
                    calibrating, lost_since = True, None
                    step = data.get("State") or f"{data.get('dir')} step {data.get('step')}"
                    context.progress(None, f"calibrating: {step}")
                case "CalibrationComplete":
                    calibrated, calibrating = True, False
                    context.progress(None, "calibrated")
                case "CalibrationFailed":
                    raise GuidingError(f"calibration failed: {data.get('Reason', 'no reason')}")
                case "StartGuiding":
                    context.progress(None, "guiding, settling")
                case "Settling":
                    distance = data.get("Distance")
                    if isinstance(distance, int | float):
                        context.progress(None, f"settling: {distance:.1f} px")
                case "StarLost":
                    if lost_since is None:
                        lost_since = asyncio.get_running_loop().time()
                    context.progress(None, "star lost: waiting for it")
                case "GuideStep":
                    lost_since = None
                case "SettleDone":
                    status = data.get("Status")
                    if status != 0:
                        reason = data.get("Error") or "timed out"
                        raise GuidingError(f"PHD2 did not settle ({reason}); it goes on guiding")
                    await self._read_calibration(client)
                    return {
                        "calibrated": calibrated,
                        "frames": data.get("TotalFrames"),
                        "dropped": data.get("DroppedFrames"),
                    }
                case "GuidingStopped" | "LoopingExposuresStopped":
                    raise GuidingError("PHD2 stopped before it settled")
                case _:
                    pass

    async def _next_frame(self, queue: asyncio.Queue[Phd2Message]) -> None:
        timeout = (self._exposure or EXPOSURE_RANGE[1]) + FIRST_FRAME_MARGIN
        async with asyncio.timeout(timeout):
            while True:
                message = await queue.get()
                if isinstance(message, Phd2Closed):
                    raise Phd2ConnectionError(f"lost PHD2: {message.reason}")
                if message.name == "LoopingExposures":
                    return
                if message.name == "LoopingExposuresStopped":
                    raise GuidingError("PHD2 stopped looping")

    async def _find_star(self, client: Phd2Client, queue: asyncio.Queue[Phd2Message]) -> None:
        region = self._star_region()
        params: dict[str, Json] | None = {"roi": region} if region is not None else None
        for attempt in range(FIND_STAR_ATTEMPTS):
            try:
                await client.call("find_star", params)
                return
            except Phd2Error as e:
                if attempt == FIND_STAR_ATTEMPTS - 1:
                    raise GuidingError(f"no guide star: {e}") from e
                await self._next_frame(queue)

    def _star_region(self) -> list[Json] | None:
        """Where to look for a guide star: the frame without its edges, as [x, y, w, h]."""
        device = self._equipment.ready_device(CAMERA)
        if device is None or self._indi is None:
            return None
        try:
            sensor = Camera(self._indi, device).sensor
        except (DeviceError, KeyError, TypeError) as e:
            log.debug("guide camera size unknown: %s", e)
            return None
        margin = max(50, round(STAR_EDGE * min(sensor.width, sensor.height)))
        width, height = sensor.width - 2 * margin, sensor.height - 2 * margin
        if width <= 0 or height <= 0:
            return None
        return [margin, margin, width, height]

    def _hold_mount(self) -> None:
        """Reserve the mount, unless the job guiding runs in holds it itself."""
        holder = self._jobs.holder(Role.MOUNT.value)
        if self._mount_hold is None and (holder is None or holder not in self._callers()):
            self._mount_hold = self._jobs.reserve("guiding", [Role.MOUNT.value])

    def _callers(self) -> set[str]:
        return {job for job in (self._starting, self._under) if job is not None}

    def _under_running(self) -> bool:
        """The job guiding goes on under has not finished yet."""
        if self._under is None:
            return False
        if self._store.get(("jobs", self._under, "state")) == "running":
            return True
        self._under = None
        return False

    def _sync_mount_hold(self) -> None:
        """Hold the mount exactly while PHD2 moves it (or a start of guiding runs).

        A job holding the mount itself (a sequence) keeps it; NOCS takes it once that
        job lets go and PHD2 still guides.
        """
        wanted = self._starting is not None or self._app_state in GUIDING_STATES
        if wanted and self._mount_hold is None and self._phd2 is not None:
            if self._jobs.holder(Role.MOUNT.value) is not None or self._under_running():
                return  # a job holds it (or is about to): it moves it only after stopping guiding
            try:
                self._hold_mount()
            except ResourceBusyError as e:
                log.warning("PHD2 guides while NOCS uses the mount: %s", e)
        elif not wanted and self._mount_hold is not None:
            self._jobs.release(self._mount_hold)
            self._mount_hold = None

    async def _read_calibration(self, client: Phd2Client) -> None:
        try:
            data = await client.call("get_calibration_data", ["Mount"])
        except Phd2Error as e:
            log.debug("no calibration data: %s", e)
            data = None
        calibration: Json = None
        if isinstance(data, dict) and data.get("calibrated") is True:
            calibration = {
                "ra_angle": data.get("xAngle"),
                "ra_rate": data.get("xRate"),
                "dec_angle": data.get("yAngle"),
                "dec_rate": data.get("yRate"),
                "declination": data.get("declination"),
            }
        self._store.set((*ROOT, "calibration"), calibration)

    async def _read_pixel_scale(self, client: Phd2Client) -> None:
        scale = await client.call("get_pixel_scale")
        if isinstance(scale, int | float) and not isinstance(scale, bool) and scale > 0:
            self._pixel_scale = float(scale)
            self._store.set((*ROOT, "pixel_scale"), round(self._pixel_scale, 4))

    async def _set_connected(self, client: Phd2Client, connected: bool) -> None:
        """PHD2 refuses while a capture ends, a moment after it says it stopped: retry."""
        deadline = asyncio.get_running_loop().time() + CAPTURE_ENDING
        while True:
            try:
                await client.call("set_connected", [connected], timeout=CONNECT_TIMEOUT)
                return
            except Phd2Error as e:
                if "capture" not in str(e) or asyncio.get_running_loop().time() > deadline:
                    raise
            await asyncio.sleep(0.5)

    async def _set_exposure(self, client: Phd2Client, exposure: float) -> None:
        low, high = EXPOSURE_RANGE
        if not low <= exposure <= high:
            raise ValueError(f"PHD2's exposure must be {low:g}..{high:g} s")
        await client.call("set_exposure", [round(exposure * 1000)])
        self._publish_exposure(exposure)

    async def _stop(self, client: Phd2Client) -> None:
        # Asked rather than taken from the events: the one telling that a loop just
        # started may not have arrived yet.
        state = await client.call("get_app_state")
        if isinstance(state, str):
            self._set_app_state(state)
        if self._app_state in IDLE_STATES:
            return
        guided = self._app_state in GUIDING_STATES
        queue: asyncio.Queue[Phd2Message] = asyncio.Queue()
        self._queues.add(queue)
        try:
            await client.call("stop_capture")
            timeout = (self._exposure or EXPOSURE_RANGE[1]) + STOP_MARGIN
            try:
                await asyncio.wait_for(self._idle.wait(), timeout)
            except TimeoutError:
                raise TimeoutError(f"PHD2 did not stop within {timeout:g} s") from None
            if guided:
                # PHD2 tells that guiding stopped, then that its loop did: left unread,
                # the second would reach the next start as the end of its own loop.
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(LOOP_STOPPED):
                        while not _ends_loop(await queue.get()):
                            pass
        finally:
            self._queues.discard(queue)

    async def _read_exposure(self, client: Phd2Client) -> None:
        milliseconds = await client.call("get_exposure")
        if isinstance(milliseconds, int | float) and milliseconds > 0:
            self._publish_exposure(milliseconds / 1000)

    def _hold_camera(self) -> None:
        if self._hold is not None:
            return
        self._hold = self._jobs.reserve("guiding", [CAMERA.value])
        self._store.set((*ROOT, "equipment"), True)
        if self._frames is not None:
            self._frames.follow(CAMERA, HOLDER, lambda: self._exposure or 0.0)

    def _release(self) -> None:
        if self._hold is None:
            return
        self._jobs.release(self._hold)
        self._hold = None
        self._store.set((*ROOT, "equipment"), False)
        if self._frames is not None:
            self._frames.unfollow(CAMERA)

    def _publish_exposure(self, exposure: float) -> None:
        self._exposure = exposure
        self._store.set((*ROOT, "exposure"), exposure)

    # -- internals ----------------------------------------------------------

    async def _sync(self, client: Phd2Client) -> None:
        """Bring PHD2's settings in line with the active profile, as far as it can now."""
        try:
            state = await client.call("get_app_state")
            if isinstance(state, str):
                self._set_app_state(state, wake=False)
            await self._sync_equipment(client)
            if not self.managed:
                await self._check_equipment(client)
                return
            profile = await client.call("get_profile")
            name = profile.get("name") if isinstance(profile, dict) else None
            self._store.set((*ROOT, "profile"), name if isinstance(name, str) else None)
        except Phd2Error as e:
            log.warning("PHD2: %s", e)
            self._publish_settings(SettingsStatus.FAILED, str(e))
            return
        desired = self._desired
        if desired is None:
            self._publish_settings(SettingsStatus.NONE, self._desired_error)
        elif name == desired.profile_name:
            self._attempted = None
            self._publish_settings(SettingsStatus.APPLIED)
        elif self._app_state not in IDLE_STATES or self._hold is not None:
            self._publish_settings(SettingsStatus.PENDING)
        elif self._attempted == desired.profile_name:
            self._publish_settings(
                SettingsStatus.FAILED,
                f"PHD2 restarted without the new settings: its service must import "
                f"{self._settings_file} (PHD2_SETTINGS)",
            )
        else:
            await self._apply(client, desired)

    async def _sync_equipment(self, client: Phd2Client) -> None:
        """Hold the camera exactly while PHD2's equipment is connected, whoever connected it."""
        connected = await client.call("get_connected")
        if connected is True and self._hold is None and self._equipment.ready_device(CAMERA):
            try:
                self._hold_camera()
            except ResourceBusyError as e:  # NOCS was using it first
                log.warning("PHD2 connected to the guide camera while NOCS used it: %s", e)
                return
            await self._read_exposure(client)
            await self._read_calibration(client)
            await self._read_pixel_scale(client)
        elif connected is False and self._hold is not None and not self._commands.locked():
            self._release()

    async def _apply(self, client: Phd2Client, desired: Phd2Settings) -> None:
        assert self._settings_file is not None
        path = self._settings_file
        try:
            await anyio.to_thread.run_sync(_write_settings, path, desired.content)
        except OSError as e:
            self._publish_settings(SettingsStatus.FAILED, f"cannot write {path}: {e}")
            return
        log.info("restarting PHD2 with settings %s", desired.profile_name)
        self._attempted = desired.profile_name
        self._publish_settings(SettingsStatus.APPLYING)
        # PHD2 may close the connection before answering.
        with contextlib.suppress(Phd2ConnectionError, TimeoutError):
            await client.call("shutdown", timeout=5)

    async def _check_equipment(self, client: Phd2Client) -> None:
        """With PHD2 as the user set it up, say when it guides with other devices."""
        current = await client.call("get_current_equipment")
        wanted = {
            "camera": self._equipment.ready_device(Role.GUIDE_CAMERA),
            "mount": self._equipment.ready_device(Role.MOUNT),
        }
        problems: list[str] = []
        for kind, device in wanted.items():
            if device is None:
                continue
            entry = current.get(kind) if isinstance(current, dict) else None
            selected = entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(selected, str) or f"[{device}]" not in selected:
                problems.append(f"PHD2's {kind} is {selected or 'not set'}, not {device}")
        self._publish_settings(SettingsStatus.USER, "; ".join(problems) or None)

    def _on_indi(self, client: IndiClient | None) -> None:
        self._indi = client
        self._refresh()

    def _refresh(self) -> None:
        """Work out the settings for the active profile as its devices come and go."""
        if self._hold is not None and (
            self._equipment.ready_device(CAMERA) is None
            or self._equipment.ready_device(Role.MOUNT) is None
        ):
            self._background(self.release())
        desired, error = self._render()
        if not self.managed:
            self._changed.set()  # to check PHD2's equipment against the new devices
        elif desired != self._desired or error != self._desired_error:
            self._desired, self._desired_error = desired, error
            self._changed.set()

    def _render(self) -> tuple[Phd2Settings | None, str | None]:
        if not self.managed:
            return None, None
        profile = self._equipment.active_profile
        profile_id = self._equipment.active
        camera = self._equipment.ready_device(Role.GUIDE_CAMERA)
        mount = self._equipment.ready_device(Role.MOUNT)
        client = self._indi
        if profile is None or profile_id is None or client is None:
            return None, None
        if camera is None or mount is None:
            return None, None
        optics = profile.guiding_optics
        if optics is None:
            train = "imaging" if profile.guiding_through_imaging else "guiding"
            return None, f"the profile has no {train} optics: PHD2 needs the focal length"
        try:
            sensor = Camera(client, camera).sensor
            rig = GuideRig(
                camera=camera,
                mount=mount,
                pixel_size=sensor.pixel_size_x,
                focal_length=optics.focal_length * optics.reducer,
                guide_rate=Mount(client, mount).guide_rate,
                indi_host=self._indi_host,
                indi_port=self._indi_port,
            )
            return render(rig, profile_id), None
        except (DeviceError, KeyError, ValueError) as e:
            log.warning("cannot render PHD2 settings: %s", e)
            return None, f"cannot describe the guide camera to PHD2: {e}"

    def _on_event(self, event: Phd2Event) -> None:
        match event.name:
            case "Version":
                version = event.data.get("PHDVersion")
                self._store.set((*ROOT, "phd2", "version"), str(version) if version else None)
            case "AppState":
                state = event.data.get("State")
                if isinstance(state, str):
                    self._set_app_state(state)
            case "Alert":
                self._alert(str(event.data.get("Msg", "")), str(event.data.get("Type", "info")))
            case "SettleBegin" | "Settling":
                self._set_settling(True)
            case "SettleDone":
                self._set_settling(False)
            case "Calibrating":
                self._store.set((*ROOT, "calibrating"), _calibration_progress(event.data))
            case "CalibrationComplete":
                self._store.set((*ROOT, "calibrating"), None)
            case "StartGuiding":
                self._history.reset()
                self._publish_stats(None)
            case "CalibrationFailed":
                self._store.set((*ROOT, "calibrating"), None)
                self._alert(f"calibration failed: {event.data.get('Reason', '')}", "error")
                self._changed.set()
            case _:
                pass
        entry = self._history.add(event.name, event.data, settling=self._settling)
        if entry is not None:
            self._publish_stats(entry)
            if self._mount_hold is None:
                self._sync_mount_hold()  # a job that held the mount may have let go
        if event.name == "StarLost":
            self._alert(f"star lost: {event.data.get('Status', '')}", "warning")
            if self._app_state == "Guiding":  # while calibrating, PHD2 still calibrates
                self._set_app_state("LostLock")
        if event.name == "LoopingExposures" and self._app_state == "Selected":
            pass  # looping with a star selected, as PHD2 says itself
        elif event.name in _STATE_OF_EVENT:
            self._set_app_state(_STATE_OF_EVENT[event.name])
        elif event.name in _QUERY_EVENTS:
            self._changed.set()  # _sync asks for the state

    def _set_settling(self, settling: bool) -> None:
        if settling != self._settling:
            self._settling = settling
            self._store.set((*ROOT, "settling"), settling)

    def _publish_stats(self, last: GuideEntry | None) -> None:
        recent = self._history.recent_rms()
        scale = self._pixel_scale

        def arcsec(pixels: float | None) -> Json:
            return round(pixels * scale, 3) if pixels is not None and scale else None

        def px(pixels: float | None) -> Json:
            return round(pixels, 3) if pixels is not None else None

        ra = recent.ra if recent else None
        dec = recent.dec if recent else None
        total = recent.total if recent else None
        peak_ra = recent.peak_ra if recent else None
        peak_dec = recent.peak_dec if recent else None
        self._store.set(
            (*ROOT, "stats"),
            {
                "seq": self._history.last_seq,
                "steps": recent.count if recent else 0,
                "rms_ra": arcsec(ra),
                "rms_dec": arcsec(dec),
                "rms_total": arcsec(total),
                "rms_ra_px": px(ra),
                "rms_dec_px": px(dec),
                "rms_total_px": px(total),
                "peak_ra_px": px(peak_ra),
                "peak_dec_px": px(peak_dec),
                "lost": self._history.lost_count(),
                "last": last.to_json() if last is not None else None,
            },
        )

    def _alert(self, message: str, kind: str) -> None:
        when = datetime.now(UTC).isoformat(timespec="seconds")
        self._store.set((*ROOT, "alert"), {"message": message, "kind": kind, "time": when})

    def _background(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _set_app_state(self, state: str, *, wake: bool = True) -> None:
        if state in IDLE_STATES:
            self._idle.set()
        else:
            self._idle.clear()
        if state == self._app_state:
            return
        was_busy = self._app_state not in IDLE_STATES
        self._app_state = state
        with self._store.transaction():
            self._store.set((*ROOT, "app_state"), state)
            if state != "Calibrating":
                self._store.set((*ROOT, "calibrating"), None)
        self._sync_mount_hold()
        if state in IDLE_STATES or state in LOOPING_STATES:
            self._set_settling(False)
        if wake and was_busy and state in IDLE_STATES:
            self._changed.set()  # pending settings may go in now

    def _status(self) -> SettingsStatus:
        value = self._store.get((*ROOT, "settings"))
        return SettingsStatus(value) if isinstance(value, str) else SettingsStatus.NONE

    def _publish_settings(self, status: SettingsStatus, error: str | None = None) -> None:
        with self._store.transaction():
            self._store.set((*ROOT, "settings"), status.value)
            self._store.set((*ROOT, "error"), error)

    def _server(self, *, connected: bool, error: str | None = None) -> dict[str, Json]:
        return {
            "host": self._host,
            "port": self._port,
            "connected": connected,
            "version": None,
            "error": error,
        }

    def _publish_server(self, *, connected: bool, error: str | None = None) -> None:
        path = (*ROOT, "phd2")
        with self._store.transaction():
            self._store.set((*path, "connected"), connected)
            self._store.set((*path, "error"), error)
            if not connected:
                self._store.set((*path, "version"), None)


_DIRECTIONS = {
    "West": "west",
    "East": "east",
    "Backlash": "backlash",
    "North": "north",
    "South": "south",
}


def _calibration_progress(data: dict[str, Json]) -> dict[str, Json]:
    """A ``Calibrating`` event as the app shows it, from its fields rather than its
    English ``State`` text, whose step number is the one PHD2 shows."""
    name = str(data.get("dir", ""))
    direction = _DIRECTIONS.get(name, "nudge" if name.startswith("Nudge") else "other")
    shown = re.search(r"(\d+)", str(data.get("State", "")))
    step = data.get("step")
    distance = data.get("dist")
    return {
        "direction": direction,
        "step": int(shown.group(1)) if shown else int(step) if isinstance(step, int) else 0,
        "distance": float(distance) if isinstance(distance, int | float) else 0.0,
    }


def _write_settings(path: FsPath, content: str) -> None:
    """Readable by PHD2's service, which may run as another user (a container)."""
    write_atomic(path, content)
    path.chmod(0o644)


def _checked(settle: Settle | None) -> Settle:
    settle = settle or Settle()
    if settle.pixels <= 0 or settle.time < 0 or settle.timeout <= 0:
        raise ValueError("settling needs a positive distance and timeout")
    return settle


def _ends_loop(message: Phd2Message) -> bool:
    return isinstance(message, Phd2Closed) or message.name == "LoopingExposuresStopped"
