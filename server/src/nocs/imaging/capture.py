"""Camera control by role: settings, cooling, and exposures run as jobs.

State layout under ``("cameras",)``, one entry per connected camera role::

    {device, exposing, remaining, temperature, can_cool, cooler, cooler_power, target, ramp,
     exposure, gain, gain_range, offset, offset_range, binning, max_binning, region,
     frame_type, sensor, bayer, field, last_frame, preview}

``field`` is what a frame covers with the role's optical train (the imaging train
for the main camera, the guiding one for the guide camera), binning and region.

INDI has no exposure time to keep, only the one of each exposure: NOCS keeps it
per role (the last one set or used), so every client shows the same.

Frames come either saved by the driver into a directory nocsd can read
(``UPLOAD_LOCAL``, main camera only) or as BLOBs (ADR 0012); either way each becomes a file that is
handed to storage when saved (main camera only, ADR 0013), analysed in the imaging
worker, and deleted afterwards when it was only for a preview (loop mode).

Workflows that run in a job of their own (autofocus, solving) take frames with
``take`` and measure their stars with ``measure``, without previews or saving.

Each camera gets its own INDI connection for images (BLOB only, for that device),
opened at the first exposure, so a frame of tens of megabytes never holds up
the connection that carries the state of every device.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path as FsPath
from pathlib import PurePosixPath
from typing import Any, Protocol

import anyio

from nocs.clock import Clock
from nocs.devices import Camera, DeviceError, FilterWheel, Frame, FrameType, Mount
from nocs.devices.camera import Region
from nocs.equipment import EquipmentService, Role, Site
from nocs.equipment.service import IndiConnection
from nocs.guiding import GuidingError, GuidingNotReadyError, Settle
from nocs.imaging.pipeline import FrameAnalysis, StarMetrics
from nocs.imaging.worker import ImageWorker
from nocs.indi import BlobMode, IndiClient, IndiEvent, PropertyDefined, PropertyUpdated
from nocs.jobs import JobContext, JobManager
from nocs.solving import field_of_view
from nocs.state import Json, Path, StateStore
from nocs.storage import FrameFacts, StorageError, StorageService
from nocs.storage.environment import number

log = logging.getLogger(__name__)

ROOT: Path = ("cameras",)
CAMERA_ROLES = (Role.MAIN_CAMERA, Role.GUIDE_CAMERA)
SAVING_ROLES = (Role.MAIN_CAMERA,)
"""Guide camera frames are only previews; PHD2 takes its own (ADR 0013)."""
LOCAL_UPLOAD_ROLES = (Role.MAIN_CAMERA,)
"""Roles whose driver may save frames itself (``UPLOAD_LOCAL``). The guide camera
always sends BLOBs: the upload mode is the device's, and PHD2 needs them (ADR 0012).
Its frames are small."""
EXPOSURE_DEFAULT = 2.0
MAX_EXPOSURE = 7200.0

FRAME_TYPES: dict[str, FrameType] = {
    "light": FrameType.LIGHT,
    "dark": FrameType.DARK,
    "bias": FrameType.BIAS,
    "flat": FrameType.FLAT,
}
FRAME_TYPE_NAMES = {value: name for name, value in FRAME_TYPES.items()}

# Properties that feed the camera state; updates to others are ignored.
_WATCHED = frozenset(
    {
        "CCD_EXPOSURE",
        "CCD_TEMPERATURE",
        "CCD_COOLER",
        "CCD_COOLER_POWER",
        "CCD_TEMP_RAMP",
        "CCD_CONTROLS",
        "CCD_GAIN",
        "CCD_OFFSET",
        "CCD_BINNING",
        "CCD_FRAME",
        "CCD_FRAME_TYPE",
        "CCD_INFO",
        "CCD_CFA",
    }
)

type ImageConnector = Callable[[str], Awaitable[IndiClient]]


class CameraNotReadyError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CameraSettings:
    exposure: float | None = None
    gain: float | None = None
    offset: float | None = None
    binning: int | None = None
    region: Region | None = None
    full_frame: bool = False
    frame_type: FrameType | None = None


@dataclass(frozen=True, slots=True)
class UploadDirs:
    """Where drivers save frames themselves (``UPLOAD_LOCAL``), as indiserver and nocsd see it."""

    driver: PurePosixPath
    local: FsPath

    def to_local(self, driver_path: str) -> FsPath:
        return self.local / PurePosixPath(driver_path).relative_to(self.driver)


@dataclass(frozen=True, slots=True)
class Shot:
    """One exposure, on disk."""

    path: FsPath
    size: int
    frame_type: FrameType
    taken: datetime
    exposure: float
    bayer: str | None


def image_connector(host: str, port: int) -> ImageConnector:
    """Opens the connection that receives one camera's images and nothing else."""

    async def connect(device: str) -> IndiClient:
        client = IndiClient(host, port)
        await client.connect(device=device)
        try:
            # BLOB mode applies to properties the server knows the client has seen.
            await client.wait_for_property(device, "CCD1")
            await client.enable_blob(device, BlobMode.ONLY, "CCD1")
        except BaseException:
            await client.close()
            raise
        return client

    return connect


def camera_summary(camera: Camera) -> dict[str, Json]:
    """The camera state published to clients (without NOCS's own fields)."""
    sensor = camera.sensor
    region = camera.region
    gain_range = camera.gain_range
    offset_range = camera.offset_range
    binning = camera.binning
    return {
        "device": camera.name,
        "exposing": camera.exposing,
        "remaining": camera.exposure_remaining,
        "temperature": camera.temperature,
        "can_cool": camera.can_cool,
        "cooler": camera.cooler_on,
        "cooler_power": camera.cooler_power,
        "ramp": camera.temperature_ramp,
        "gain": camera.gain,
        "gain_range": {"min": gain_range.min, "max": gain_range.max} if gain_range else None,
        "offset": camera.offset,
        "offset_range": (
            {"min": offset_range.min, "max": offset_range.max} if offset_range else None
        ),
        "binning": [binning[0], binning[1]],
        "max_binning": camera.max_binning,
        "region": {
            "x": region.x,
            "y": region.y,
            "width": region.width,
            "height": region.height,
        },
        "frame_type": FRAME_TYPE_NAMES[camera.frame_type],
        "sensor": {
            "width": sensor.width,
            "height": sensor.height,
            "pixel_size": sensor.pixel_size_x,
            "bits": sensor.bits_per_pixel,
        },
        "bayer": camera.bayer_pattern,
    }


MAX_SERIES = 1000


class Guider(Protocol):
    """Dithering and guiding figures for frames (``GuidingService``)."""

    @property
    def guiding(self) -> bool: ...

    def guide_pixels(self, main_pixels: float) -> float: ...

    async def dither(
        self, context: JobContext, pixels: float, *, settle: Settle | None, ra_only: bool
    ) -> Json: ...

    def frame_guiding(self, start: float, end: float) -> dict[str, Json] | None: ...


@dataclass(frozen=True, slots=True)
class DitherPlan:
    """Dither before every ``every``-th frame of a series, while PHD2 guides (ADR 0024)."""

    every: int
    pixels: float
    """Main camera pixels (converted to the guide camera's)."""
    settle: Settle = field(default_factory=Settle)
    ra_only: bool = False


def _exposure_resources(role: Role) -> list[str]:
    """What an exposure locks: a filter change or a focuser move would spoil a main frame.

    Loops lock only the camera, so focusing and changing filters while looping work.
    """
    if role is Role.MAIN_CAMERA:
        return [role.value, Role.FILTER_WHEEL.value, Role.FOCUSER.value]
    return [role.value]


def _check_exposure(seconds: float) -> None:
    if not 0 <= seconds <= MAX_EXPOSURE:
        raise ValueError(f"exposure must be 0..{MAX_EXPOSURE:g} s")


class CaptureService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        equipment: EquipmentService,
        bridge: IndiConnection,
        connect_images: ImageConnector,
        worker: ImageWorker,
        storage: StorageService,
        data_dir: FsPath,
        uploads: UploadDirs | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._equipment = equipment
        self._connect_images = connect_images
        self._worker = worker
        self._storage = storage
        self._uploads = uploads
        self._clock = clock
        self._incoming_dir = data_dir / "incoming"
        self._client: IndiClient | None = bridge.client
        self._remove_listener = lambda: None
        self._devices: dict[Role, str] = {}
        """Camera roles that are ready, and their INDI device."""
        self._published: dict[Role, dict[str, Json]] = {}
        self._targets: dict[Role, float | None] = {}
        self._exposures: dict[Role, float] = {}
        self._last_frames: dict[Role, Json] = {}
        self._previews: dict[Role, Json] = {}
        self._images: dict[Role, IndiClient] = {}
        self._tasks: set[asyncio.Task[object]] = set()
        self._guider: Guider | None = None
        self._used_by: dict[Role, str] = {}
        """Cameras another client drives (PHD2), whose frames NOCS only previews."""
        self._following: dict[Role, asyncio.Task[None]] = {}

        # Frames left by a previous run (stopped mid-exposure) are of no use now.
        for leftover in self._incoming_dir.glob("*"):
            leftover.unlink(missing_ok=True)
        store.set(ROOT, {})
        self._unwatch_bridge = bridge.watch(self._on_client)
        self._unwatch_equipment = equipment.add_listener(self._refresh)
        self._on_client(bridge.client)

    # -- commands ---------------------------------------------------------

    def camera(self, role: Role) -> Camera:
        name = self._devices.get(role)
        if self._client is None or name is None:
            raise CameraNotReadyError(f"{role.value} is not connected")
        return Camera(self._client, name, self._images.get(role))

    async def configure(self, role: Role, settings: CameraSettings) -> None:
        """Change exposure settings; refused while the camera is busy with a job."""
        self._jobs.check_free([role.value])
        camera = self.camera(role)
        if settings.exposure is not None:
            _check_exposure(settings.exposure)
            self._set_exposure(role, settings.exposure)
        if settings.binning is not None:
            if not 1 <= settings.binning <= camera.max_binning:
                raise ValueError(f"binning must be 1..{camera.max_binning}")
            await camera.set_binning(settings.binning)
        if settings.full_frame:
            await camera.set_region(None)
        elif settings.region is not None:
            await camera.set_region(settings.region)
        if settings.gain is not None:
            await camera.set_gain(settings.gain)
        if settings.offset is not None:
            await camera.set_offset(settings.offset)
        if settings.frame_type is not None:
            await camera.set_frame_type(settings.frame_type)

    async def set_cooling(
        self, role: Role, on: bool, target: float | None = None, ramp: float | None = None
    ) -> None:
        """Cool to ``target`` °C (at most ``ramp`` °C/min), or switch the cooler off.

        Reaching the target can take many minutes; the state shows the progress.
        """
        camera = self.camera(role)
        if not camera.can_cool:
            raise DeviceError(f"{camera.name} has no cooler")
        if ramp is not None:
            await camera.set_temperature_ramp(ramp)
        if on:
            if target is None:
                raise ValueError("a target temperature is needed to cool")
            await camera.set_temperature(target)
            if camera.cooler_on is not None:
                await camera.set_cooler(True)
            self._targets[role] = target
        else:
            if camera.cooler_on is not None:
                await camera.set_cooler(False)
            self._targets[role] = None
        self._publish(role)

    def use_guider(self, guider: Guider) -> None:
        """Where series dither, and where saved frames get their guiding figures."""
        self._guider = guider

    def expose(
        self,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        save: bool | None = None,
        count: int = 1,
        dither: DitherPlan | None = None,
    ) -> str:
        """Start an exposure job, of ``count`` frames; returns its id.

        Frames of the main camera are saved unless ``save`` is false; those of the
        guide camera never are. A series of the main camera dithers by ``dither``
        between its frames while PHD2 guides (ADR 0024).
        """
        _check_exposure(seconds)
        if save is None:
            save = role in SAVING_ROLES
        elif save and role not in SAVING_ROLES:
            raise ValueError(f"frames of the {role.value} are not saved, only previewed")
        if not 1 <= count <= MAX_SERIES:
            raise ValueError(f"a series is 1..{MAX_SERIES} frames")
        if dither is not None:
            if role is not Role.MAIN_CAMERA:
                raise ValueError("only series of the main camera dither")
            if dither.every < 1 or dither.pixels <= 0:
                raise ValueError("dithering needs a positive amount, every 1 frame or more")
        self.camera(role)  # fail now, not inside the job, if it is not connected

        async def run(context: JobContext) -> Json:
            if count == 1:
                return await self._expose(context, role, seconds, frame_type, save)
            return await self._series(context, role, seconds, frame_type, save, count, dither)

        job_id = self._jobs.start("expose", _exposure_resources(role), run)
        self._set_exposure(role, seconds)
        return job_id

    def loop(self, role: Role, seconds: float, frame_type: FrameType | None = None) -> str:
        """Expose again and again, keeping only previews, until the job is cancelled."""
        _check_exposure(seconds)
        self.camera(role)

        async def run(context: JobContext) -> Json:
            count = 0
            while True:
                count += 1
                shot = await self.take(context, role, seconds, frame_type, f"frame {count}: ")
                # Analysis overlaps the next exposure; a frame still waiting for the
                # worker when the next one arrives is skipped.
                self._background(self._preview(role, shot, discard=True))

        job_id = self._jobs.start("loop", [role.value], run)
        self._set_exposure(role, seconds)
        return job_id

    async def take(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        label: str = "",
    ) -> Shot:
        """One exposure inside ``context``'s job, left in a file of its own for the caller.

        The job must hold the camera's role. The frame is neither saved nor
        previewed: the caller measures it (``measure``) or hands it on, and
        deletes it. Progress goes to the job, each message after ``label``.
        """
        _check_exposure(seconds)
        if self._jobs.holder(role.value) != context.id:
            raise RuntimeError(f"job {context.id} does not hold the {role.value}")
        return await self._take(context, role, seconds, frame_type, label)

    async def measure(self, shot: Shot, *, discard: bool = True) -> StarMetrics:
        """Star count and HFR of a frame from ``take``, deleting its file unless told not to."""
        try:
            return await self._worker.measure(str(shot.path), shot.bayer)
        finally:
            if discard:
                await anyio.to_thread.run_sync(lambda: shot.path.unlink(missing_ok=True))

    def follow(self, role: Role, by: str, exposure: Callable[[], float]) -> None:
        """Preview the frames ``by`` (PHD2) takes with this camera (ADR 0023).

        The caller keeps NOCS's own exposures away from the camera meanwhile.
        ``exposure`` says how long its frames are, in seconds.
        """
        self._used_by[role] = by
        self._publish(role)
        if role not in self._following:
            task = asyncio.get_running_loop().create_task(self._follow(role, exposure))
            self._following[role] = task

    def unfollow(self, role: Role) -> None:
        """Stop previewing another client's frames; the camera is NOCS's again."""
        self._used_by.pop(role, None)
        if (task := self._following.pop(role, None)) is not None:
            task.cancel()
        self._publish(role)

    async def close(self) -> None:
        for task in list(self._following.values()):
            task.cancel()
        self._unwatch_bridge()
        self._unwatch_equipment()
        self._remove_listener()
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.wait(self._tasks)
        for role in list(self._images):
            await self._close_images(role)

    # -- internals: exposures ---------------------------------------------

    async def _series(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None,
        save: bool,
        count: int,
        dither: DitherPlan | None,
    ) -> Json:
        frames: list[Json] = []
        dithers = 0
        warnings: list[Json] = []
        for index in range(count):
            label = f"frame {index + 1}/{count}: "
            if dither is not None and index > 0 and index % dither.every == 0:
                problem = await self._dither(context, dither, label)
                if problem is None:
                    dithers += 1
                else:
                    log.warning("%s%s", label, problem)
                    warnings.append(f"{label}{problem}")
            frames.append(await self._expose(context, role, seconds, frame_type, save, label))
        return {"frames": frames, "dithers": dithers, "warnings": warnings}

    async def _dither(self, context: JobContext, plan: DitherPlan, label: str) -> str | None:
        """Dither before a frame; what went wrong (the series goes on), or None."""
        guider = self._guider
        if guider is None or not guider.guiding:
            return "not dithering: PHD2 is not guiding"
        context.progress(None, f"{label}dithering")
        try:
            pixels = guider.guide_pixels(plan.pixels)
            await guider.dither(context, pixels, settle=plan.settle, ra_only=plan.ra_only)
        except (GuidingError, GuidingNotReadyError, ValueError, ConnectionError, TimeoutError) as e:
            return f"dither: {e}"
        return None

    async def _expose(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None,
        save: bool,
        label: str = "",
    ) -> Json:
        # PHD2 stamps guide steps with the system clock, not NOCS's corrected one.
        started = time.time()
        shot = await self.take(context, role, seconds, frame_type, label)
        ended = time.time()
        guiding = None
        if role is Role.MAIN_CAMERA and self._guider is not None:
            guiding = self._guider.frame_guiding(started, ended)
        result: dict[str, Json] = {
            "exposure": seconds,
            "frame_type": FRAME_TYPE_NAMES[shot.frame_type],
            "format": shot.path.suffix,
            "size": shot.size,
            "time": shot.taken.isoformat(timespec="seconds"),
            "id": None,
            "path": None,
            "destination": None,
            "guiding": guiding,
        }
        frame_id: int | None = None
        if save:
            context.progress(None, f"{label}saving")
            facts = self._facts(role, shot)
            try:
                saved = await anyio.to_thread.run_sync(self._storage.save, facts)
            except Exception as e:
                kept = await anyio.to_thread.run_sync(self._storage.keep_unsaved, shot.path)
                if isinstance(e, StorageError) and kept is not None:
                    raise StorageError(f"{e} (the frame was kept in {kept})") from e
                raise
            shot = Shot(saved.path, shot.size, shot.frame_type, shot.taken, seconds, shot.bayer)
            frame_id = saved.id
            result |= {
                "id": saved.id,
                "path": str(saved.relative),
                "destination": saved.destination,
            }
        self._last_frames[role] = result
        self._publish(role)
        context.progress(None, f"{label}making the preview")
        analysis = await self._preview(role, shot, discard=not save)
        if frame_id is not None and analysis is not None:
            await anyio.to_thread.run_sync(
                self._storage.set_metrics, frame_id, analysis.stars, analysis.hfr
            )
        if frame_id is not None and guiding is not None:
            await anyio.to_thread.run_sync(self._storage.set_guiding, frame_id, guiding)
        return result

    def _facts(self, role: Role, shot: Shot) -> FrameFacts:
        """What storage needs to know about a frame, read now from the devices and profile."""
        camera = self.camera(role)
        filter: str | None = None
        wheel = self._equipment.ready_device(Role.FILTER_WHEEL)
        if wheel is not None and self._client is not None:
            try:
                filter = FilterWheel(self._client, wheel).filter
            except (DeviceError, KeyError) as e:
                log.debug("no filter name for the frame: %s", e)
        profile = self._equipment.active_profile
        site = profile.site if profile is not None else None
        if site is None:
            site = self._mount_site()
        return FrameFacts(
            source=shot.path,
            frame_type=FRAME_TYPE_NAMES[shot.frame_type],
            exposure=shot.exposure,
            arrived=shot.taken,
            camera=camera.name,
            gain=camera.gain,
            offset=camera.offset,
            binning=camera.binning[0],
            temperature=camera.temperature,
            cooler_target=self._targets.get(role),
            filter=filter,
            profile=self._equipment.active,
            site=site,
            optics=profile.imaging if profile is not None else None,
            clock_correction=self._clock.correction if self._clock is not None else 0.0,
            ambient=number(self._store, ("weather", "temperature")),
            humidity=number(self._store, ("weather", "humidity")),
            dew_point=number(self._store, ("weather", "dew_point")),
        )

    def _mount_site(self) -> Site | None:
        """The site the mount has, for a profile without one.

        The driver writes the mount's latitude and longitude in the header itself;
        this adds its elevation.
        """
        mount = self._equipment.ready_device(Role.MOUNT)
        if mount is None or self._client is None:
            return None
        try:
            location = Mount(self._client, mount).location
        except (DeviceError, KeyError) as e:
            log.debug("no site from the mount for the frame: %s", e)
            return None
        if location is None:
            return None
        return Site(
            latitude=location.latitude,
            longitude=location.longitude,
            elevation=location.elevation,
        )

    async def _take(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None,
        label: str = "",
    ) -> Shot:
        """One exposure, left in a file of its own that nobody keeps yet."""
        name = self.camera(role).name
        client = self._client
        assert client is not None
        uploads = self._uploads if role in LOCAL_UPLOAD_ROLES else None
        if uploads is None:
            images = self._images.get(role)
            if images is None or not images.connected:
                context.progress(None, f"{label}opening the image connection")
                images = await self._connect_images(name)
                self._images[role] = images
            camera = Camera(client, name, images)
        else:
            camera = Camera(client, name)

        def on_event(event: IndiEvent) -> None:
            match event:
                case PropertyUpdated(property=prop) if (
                    prop.device == name and prop.name == "CCD_EXPOSURE"
                ):
                    remaining = camera.exposure_remaining
                    if remaining is not None and seconds > 0:
                        fraction = 1 - remaining / seconds
                        context.progress(fraction, f"{label}{remaining:.0f} s left")
                    elif remaining is None:
                        context.progress(None, f"{label}downloading")
                case _:
                    pass

        if uploads is not None:
            await anyio.to_thread.run_sync(self._clear_uploads, role)
        context.progress(0.0, f"{label}exposing {seconds:g} s")
        remove = client.add_listener(on_event)
        try:
            if uploads is not None:
                log.debug("%s: exposing %g s", role.value, seconds)
                written = await camera.expose_to_file(
                    seconds,
                    frame_type,
                    directory=str(uploads.driver),
                    prefix=f"{role.value}_XXX",
                )
                log.debug("%s: driver saved %s", role.value, written)
                path = await anyio.to_thread.run_sync(self._claim, uploads.to_local(written), role)
                log.debug("%s: claimed as %s", role.value, path.name)
                try:
                    size = (await anyio.to_thread.run_sync(path.stat)).st_size
                except BaseException:
                    path.unlink(missing_ok=True)  # cancelled: nobody will use it
                    raise
            else:
                frame = await camera.expose(seconds, frame_type)
                path = await anyio.to_thread.run_sync(self._write_incoming, frame, role)
                size = len(frame.data)
        finally:
            remove()
        used_type = frame_type if frame_type is not None else camera.frame_type
        taken = self._clock.now() if self._clock is not None else datetime.now(UTC)
        return Shot(path, size, used_type, taken, seconds, camera.bayer_pattern)

    async def _follow(self, role: Role, exposure: Callable[[], float]) -> None:
        """Turn each frame the camera sends into a preview, skipping to the newest."""
        latest: Frame | None = None
        arrived = asyncio.Event()

        def on_frame(frame: Frame) -> None:
            nonlocal latest
            latest = frame
            arrived.set()

        try:
            camera = await self._image_camera(role)
            stop = camera.watch_frames(on_frame, exposure)
        except (CameraNotReadyError, DeviceError, ConnectionError, TimeoutError) as e:
            log.warning(
                "cannot preview %s's frames of the %s: %s", self._used_by.get(role), role.value, e
            )
            return
        try:
            while True:
                await arrived.wait()
                arrived.clear()
                frame, latest = latest, None
                if frame is None:
                    continue
                path = await anyio.to_thread.run_sync(self._write_incoming, frame, role)
                taken = self._clock.now() if self._clock is not None else datetime.now(UTC)
                shot = Shot(
                    path,
                    len(frame.data),
                    camera.frame_type,
                    taken,
                    frame.exposure,
                    camera.bayer_pattern,
                )
                await self._preview(role, shot, discard=True)
        finally:
            stop()

    async def _image_camera(self, role: Role) -> Camera:
        """The camera with its image connection, opening it if needed."""
        name = self.camera(role).name
        images = self._images.get(role)
        if images is None or not images.connected:
            images = await self._connect_images(name)
            self._images[role] = images
        assert self._client is not None
        return Camera(self._client, name, images)

    async def _preview(self, role: Role, shot: Shot, *, discard: bool) -> FrameAnalysis | None:
        """Analyse a frame in the worker and publish its preview; never raises."""
        try:
            analysis = await self._worker.analyze(role.value, str(shot.path), shot.bayer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("no preview for %s: %s", shot.path.name, e)
            analysis = None
        finally:
            if discard:
                await anyio.to_thread.run_sync(lambda: shot.path.unlink(missing_ok=True))
        if analysis is None:
            return None  # failed, or a newer frame replaced it
        self._previews[role] = {
            "url": f"/api/previews/{FsPath(analysis.preview).name}",
            "width": analysis.width,
            "height": analysis.height,
            "color": analysis.color,
            "stars": analysis.stars,
            "hfr": analysis.hfr,
            "histogram": list[Json](analysis.histogram.counts),
            "histogram_start": analysis.histogram.start,
            "histogram_step": analysis.histogram.step,
            "minimum": analysis.histogram.minimum,
            "maximum": analysis.histogram.maximum,
            "exposure": shot.exposure,
            "frame_type": FRAME_TYPE_NAMES[shot.frame_type],
            "time": shot.taken.isoformat(timespec="seconds"),
            "seconds": analysis.seconds,
        }
        self._publish(role)
        return analysis

    def _claim(self, path: FsPath, role: Role) -> FsPath:
        """Move a frame the driver saved out of the upload directory (blocking).

        Drivers number their files from what is in the directory, so a name can come
        back once files are moved away: each frame gets a unique name of its own at
        once, and the upload directory only ever holds frames being written. The
        target must not exist: ext4 flushes a file renamed over another one to disk
        first (auto_da_alloc), ~2 s for a 26 MP frame on a microSD.
        """
        self._incoming_dir.mkdir(parents=True, exist_ok=True)
        target = self._incoming_dir / f"{role.value}_{uuid.uuid4().hex}{path.suffix}"
        shutil.move(path, target)
        return target

    def _clear_uploads(self, role: Role) -> None:
        """Delete frames a driver saved after their exposure was cancelled (blocking).

        Only one exposure per camera runs at a time (the job lock) and finished
        frames are moved away at once, so before a new exposure any file of this
        camera in the upload directory is an orphan.
        """
        assert self._uploads is not None
        for orphan in self._uploads.local.glob(f"{role.value}_*"):
            log.info("deleting %s, left by a cancelled exposure", orphan.name)
            orphan.unlink(missing_ok=True)

    def _write_incoming(self, frame: Frame, role: Role) -> FsPath:
        """Put a BLOB in a file of its own (blocking: run in a thread)."""
        self._incoming_dir.mkdir(parents=True, exist_ok=True)
        extension = frame.format if frame.format.startswith(".") else f".{frame.format}"
        fd, name = tempfile.mkstemp(
            dir=self._incoming_dir, prefix=f"{role.value}_", suffix=extension
        )
        with os.fdopen(fd, "wb") as f:
            f.write(frame.data)
        return FsPath(name)

    def _background(self, coro: Coroutine[Any, Any, object]) -> None:
        task: asyncio.Task[object] = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)  # keep a reference until it is done
        task.add_done_callback(self._tasks.discard)

    async def _close_images(self, role: Role) -> None:
        images = self._images.pop(role, None)
        if images is not None:
            await images.close()

    # -- internals: state -------------------------------------------------

    def _on_client(self, client: IndiClient | None) -> None:
        self._remove_listener()
        self._remove_listener = lambda: None
        self._client = client
        if client is not None:
            self._remove_listener = client.add_listener(self._on_event)
        self._refresh()

    def _refresh(self) -> None:
        """Follow the camera roles as the equipment connects and disconnects."""
        for role in CAMERA_ROLES:
            name = self._equipment.ready_device(role) if self._client is not None else None
            if name == self._devices.get(role):
                continue
            if (images := self._images.pop(role, None)) is not None:
                # Useless now; closing it is async.
                self._background(images.close())
            if (following := self._following.pop(role, None)) is not None:
                following.cancel()
            self._published.pop(role, None)
            self._targets.pop(role, None)
            self._previews.pop(role, None)
            if name is None:
                self._devices.pop(role, None)
                self._store.delete((*ROOT, role.value))
            else:
                self._devices[role] = name
                self._publish(role)

    def _on_event(self, event: IndiEvent) -> None:
        match event:
            case PropertyUpdated(property=prop) | PropertyDefined(property=prop) if (
                prop.name in _WATCHED
            ):
                for role, name in self._devices.items():
                    if name == prop.device:
                        self._publish(role)
            case _:
                pass

    def _set_exposure(self, role: Role, seconds: float) -> None:
        self._exposures[role] = seconds
        self._publish(role)

    def _field(self, role: Role) -> dict[str, Json] | None:
        profile = self._equipment.active_profile
        optics = None
        if profile is not None:
            optics = profile.imaging if role is Role.MAIN_CAMERA else profile.guiding_optics
        if optics is None:
            return None
        camera = self.camera(role)
        binning = max(1, camera.binning[0])
        region = camera.region
        field = field_of_view(
            optics, camera.sensor, binning, (region.width // binning, region.height // binning)
        )
        if field is None:
            return None
        return {
            "focal_length": field.focal_length,
            "scale": field.scale,
            "width": field.width,
            "height": field.height,
        }

    def _publish(self, role: Role) -> None:
        try:
            summary = camera_summary(self.camera(role))
        except (CameraNotReadyError, DeviceError, KeyError, TypeError, StopIteration) as e:
            log.debug("camera %s not publishable yet: %s", role.value, e)
            return
        summary["target"] = self._targets.get(role)
        summary["field"] = self._field(role)
        summary["exposure"] = self._exposures.get(role, EXPOSURE_DEFAULT)
        summary["last_frame"] = self._last_frames.get(role)
        summary["preview"] = self._previews.get(role)
        summary["used_by"] = self._used_by.get(role)
        previous = self._published.get(role)
        path = (*ROOT, role.value)
        if previous is None:
            self._store.set(path, summary)
        else:
            changed = {k: v for k, v in summary.items() if previous.get(k) != v}
            if not changed:
                return
            with self._store.transaction():
                for key, value in changed.items():
                    self._store.set((*path, key), value)
        self._published[role] = summary
