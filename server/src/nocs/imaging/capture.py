"""Camera control by role: settings, cooling, and exposures run as jobs.

State layout under ``("cameras",)``, one entry per connected camera role::

    {device, exposing, remaining, temperature, cooler, cooler_power, target, ramp,
     gain, gain_range, offset, offset_range, binning, max_binning, region,
     frame_type, sensor, bayer, last_frame, preview}

Frames come either saved by the driver into a directory nocsd can read
(``UPLOAD_LOCAL``) or as BLOBs (ADR 0012); either way each becomes a file that is
handed to storage when saved (main camera only, ADR 0013), analysed in the imaging
worker, and deleted afterwards when it was only for a preview (loop mode).

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
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path as FsPath
from pathlib import PurePosixPath
from typing import Any

import anyio

from nocs.devices import Camera, DeviceError, FilterWheel, Frame, FrameType
from nocs.devices.camera import Region
from nocs.equipment import EquipmentService, Role
from nocs.equipment.service import IndiConnection
from nocs.imaging.pipeline import FrameAnalysis
from nocs.imaging.worker import ImageWorker
from nocs.indi import BlobMode, IndiClient, IndiEvent, PropertyDefined, PropertyUpdated
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, Path, StateStore
from nocs.storage import FrameFacts, StorageError, StorageService

log = logging.getLogger(__name__)

ROOT: Path = ("cameras",)
CAMERA_ROLES = (Role.MAIN_CAMERA, Role.GUIDE_CAMERA)
SAVING_ROLES = (Role.MAIN_CAMERA,)
"""Guide camera frames are only previews; PHD2 takes its own (ADR 0013)."""

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
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._equipment = equipment
        self._connect_images = connect_images
        self._worker = worker
        self._storage = storage
        self._uploads = uploads
        self._incoming_dir = data_dir / "incoming"
        self._client: IndiClient | None = bridge.client
        self._remove_listener = lambda: None
        self._devices: dict[Role, str] = {}
        """Camera roles that are ready, and their INDI device."""
        self._published: dict[Role, dict[str, Json]] = {}
        self._targets: dict[Role, float | None] = {}
        self._last_frames: dict[Role, Json] = {}
        self._previews: dict[Role, Json] = {}
        self._images: dict[Role, IndiClient] = {}
        self._tasks: set[asyncio.Task[object]] = set()

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
        if camera.temperature is None:
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

    def expose(
        self,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        save: bool | None = None,
    ) -> str:
        """Start an exposure job; returns its id.

        Frames of the main camera are saved unless ``save`` is false; those of the
        guide camera never are.
        """
        if seconds < 0:
            raise ValueError("exposure must not be negative")
        if save is None:
            save = role in SAVING_ROLES
        elif save and role not in SAVING_ROLES:
            raise ValueError(f"frames of the {role.value} are not saved, only previewed")
        self.camera(role)  # fail now, not inside the job, if it is not connected

        async def run(context: JobContext) -> Json:
            return await self._expose(context, role, seconds, frame_type, save)

        return self._jobs.start("expose", [role.value], run)

    def loop(self, role: Role, seconds: float, frame_type: FrameType | None = None) -> str:
        """Expose again and again, keeping only previews, until the job is cancelled."""
        if seconds < 0:
            raise ValueError("exposure must not be negative")
        self.camera(role)

        async def run(context: JobContext) -> Json:
            count = 0
            while True:
                count += 1
                shot = await self._take(context, role, seconds, frame_type, f"frame {count}: ")
                # Analysis overlaps the next exposure; a frame still waiting for the
                # worker when the next one arrives is skipped.
                self._background(self._preview(role, shot, discard=True))

        return self._jobs.start("loop", [role.value], run)

    async def close(self) -> None:
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

    async def _expose(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None,
        save: bool,
    ) -> Json:
        shot = await self._take(context, role, seconds, frame_type)
        result: dict[str, Json] = {
            "exposure": seconds,
            "frame_type": FRAME_TYPE_NAMES[shot.frame_type],
            "format": shot.path.suffix,
            "size": shot.size,
            "time": shot.taken.isoformat(timespec="seconds"),
            "id": None,
            "path": None,
            "destination": None,
        }
        frame_id: int | None = None
        if save:
            context.progress(None, "saving")
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
        context.progress(None, "making the preview")
        analysis = await self._preview(role, shot, discard=not save)
        if frame_id is not None and analysis is not None:
            await anyio.to_thread.run_sync(
                self._storage.set_metrics, frame_id, analysis.stars, analysis.hfr
            )
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
            site=profile.site if profile is not None else None,
            optics=profile.imaging if profile is not None else None,
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
        if self._uploads is None:
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

        if self._uploads is not None:
            await anyio.to_thread.run_sync(self._clear_uploads, role)
        context.progress(0.0, f"{label}exposing {seconds:g} s")
        remove = client.add_listener(on_event)
        try:
            if self._uploads is not None:
                log.debug("%s: exposing %g s", role.value, seconds)
                written = await camera.expose_to_file(
                    seconds,
                    frame_type,
                    directory=str(self._uploads.driver),
                    prefix=f"{role.value}_XXX",
                )
                log.debug("%s: driver saved %s", role.value, written)
                path = await anyio.to_thread.run_sync(
                    self._claim, self._uploads.to_local(written), role
                )
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
        return Shot(path, size, used_type, datetime.now(UTC), seconds, camera.bayer_pattern)

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
            "histogram": list[Json](analysis.histogram),
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

    def _publish(self, role: Role) -> None:
        try:
            summary = camera_summary(self.camera(role))
        except (CameraNotReadyError, DeviceError, KeyError, TypeError, StopIteration) as e:
            log.debug("camera %s not publishable yet: %s", role.value, e)
            return
        summary["target"] = self._targets.get(role)
        summary["last_frame"] = self._last_frames.get(role)
        summary["preview"] = self._previews.get(role)
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
