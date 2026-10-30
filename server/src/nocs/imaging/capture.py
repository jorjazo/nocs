"""Camera control by role: settings, cooling, and exposures run as jobs.

State layout under ``("cameras",)``, one entry per connected camera role::

    {device, exposing, remaining, temperature, cooler, cooler_power, target, ramp,
     gain, gain_range, offset, offset_range, binning, max_binning, region,
     frame_type, sensor, bayer, last_frame}

Each camera gets its own INDI connection for images (BLOB only, for that device),
opened at the first exposure, so a frame of tens of megabytes never holds up
the connection that carries the state of every device.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path as FsPath
from typing import Any

import anyio

from nocs.devices import Camera, DeviceError, Frame, FrameType
from nocs.devices.camera import Region
from nocs.equipment import EquipmentService, Role
from nocs.equipment.service import IndiConnection
from nocs.indi import BlobMode, IndiClient, IndiEvent, PropertyDefined, PropertyUpdated
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("cameras",)
CAMERA_ROLES = (Role.MAIN_CAMERA, Role.GUIDE_CAMERA)

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
        data_dir: FsPath,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._equipment = equipment
        self._connect_images = connect_images
        self._frames_dir = data_dir / "frames"
        self._client: IndiClient | None = bridge.client
        self._remove_listener = lambda: None
        self._devices: dict[Role, str] = {}
        """Camera roles that are ready, and their INDI device."""
        self._published: dict[Role, dict[str, Json]] = {}
        self._targets: dict[Role, float | None] = {}
        self._last_frames: dict[Role, Json] = {}
        self._images: dict[Role, IndiClient] = {}
        self._tasks: set[asyncio.Task[None]] = set()

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
        self, role: Role, seconds: float, frame_type: FrameType | None = None, save: bool = True
    ) -> str:
        """Start an exposure job; returns its id."""
        if seconds < 0:
            raise ValueError("exposure must not be negative")
        self.camera(role)  # fail now, not inside the job, if it is not connected

        async def run(context: JobContext) -> Json:
            return await self._expose(context, role, seconds, frame_type, save)

        return self._jobs.start("expose", [role.value], run)

    async def close(self) -> None:
        self._unwatch_bridge()
        self._unwatch_equipment()
        self._remove_listener()
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
        name = self.camera(role).name
        client = self._client
        assert client is not None
        images = self._images.get(role)
        if images is None or not images.connected:
            context.progress(None, "opening the image connection")
            images = await self._connect_images(name)
            self._images[role] = images
        camera = Camera(client, name, images)

        def on_event(event: IndiEvent) -> None:
            match event:
                case PropertyUpdated(property=prop) if (
                    prop.device == name and prop.name == "CCD_EXPOSURE"
                ):
                    remaining = camera.exposure_remaining
                    if remaining is not None and seconds > 0:
                        context.progress(1 - remaining / seconds, f"{remaining:.0f} s left")
                    elif remaining is None:
                        context.progress(None, "downloading")
                case _:
                    pass

        context.progress(0.0, f"exposing {seconds:g} s")
        remove = client.add_listener(on_event)
        try:
            frame = await camera.expose(seconds, frame_type)
        finally:
            remove()
        taken = datetime.now(UTC)
        used_type = frame_type if frame_type is not None else camera.frame_type
        result: dict[str, Json] = {
            "exposure": seconds,
            "frame_type": FRAME_TYPE_NAMES[used_type],
            "format": frame.format,
            "size": len(frame.data),
            "time": taken.isoformat(timespec="seconds"),
            "path": None,
        }
        if save:
            context.progress(None, "saving")
            path = await anyio.to_thread.run_sync(
                self._write, frame, role, FRAME_TYPE_NAMES[used_type], taken
            )
            result["path"] = str(path)
        self._last_frames[role] = result
        self._publish(role)
        return result

    def _write(self, frame: Frame, role: Role, frame_type: str, taken: datetime) -> FsPath:
        """Save a frame under ``frames/<date>/``; never overwrites (blocking: run in a thread)."""
        directory = self._frames_dir / taken.strftime("%Y-%m-%d")
        directory.mkdir(parents=True, exist_ok=True)
        extension = frame.format if frame.format.startswith(".") else f".{frame.format}"
        stem = f"{taken:%Y%m%d-%H%M%S}_{role.value}_{frame_type}_{frame.exposure:g}s"
        for attempt in range(1000):
            path = directory / (
                f"{stem}{extension}" if attempt == 0 else f"{stem}_{attempt}{extension}"
            )
            try:
                with path.open("xb") as f:
                    f.write(frame.data)
            except FileExistsError:
                continue
            return path
        raise OSError(f"cannot find a free file name for {stem}")

    def _background(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
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
