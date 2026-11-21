"""The Video view's work: the main camera's video stream, its preview and its recordings.

Lucky imaging of the Moon, the Sun and the planets takes thousands of short frames;
the driver does that part. INDI's stream manager reads the camera as fast as it goes
and records SER files itself, straight to the storage destination (indiserver shares
the box's filesystem). nocsd sets the stream up, turns a few frames a second into
previews (:mod:`nocs.video.frames`), and watches each recording grow.

Streaming is a job (``video``) that holds the main camera until it is stopped, so
Explore, Sequences and Plan cannot use it meanwhile. A recording also holds the
mount, the focuser and the filter wheel: nothing moves the image while it is
recorded.

The region of interest is read out by the camera (``CCD_FRAME``): only that makes the
stream faster (a ZWO ASI2600 gives 125 fps at 640x480, 12 at full frame). Drivers that
stream the whole sensor anyway (the CCD simulator) get it cut out by the stream manager
(``CCD_STREAM_FRAME``). The stream runs at 1x1 binning.

State under ``("video",)``::

    {job, streaming, exposure, gain, depth, region, fps, frame, recording, recordings,
     error}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import struct
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import anyio

from nocs.devices import Camera, DeviceError, Frame
from nocs.devices.camera import Recording, Region
from nocs.equipment import Role
from nocs.equipment.profiles import write_atomic
from nocs.indi import IndiClient
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, StateStore
from nocs.state import Path as StatePath
from nocs.storage import StorageService, VideoPlace
from nocs.storage.layout import clean
from nocs.video.frames import FrameError, Rendered, render
from nocs.video.ser import HEADER, SerError, SerHeader, frames_written, read_header

log = logging.getLogger(__name__)

ROOT: StatePath = ("video",)
KIND = "video"
RECORDING_KIND = "recording"
RECORDING_HOLDS = (Role.MOUNT.value, Role.FOCUSER.value, Role.FILTER_WHEEL.value)
"""What a recording keeps still besides the camera the stream holds."""
EXPOSURE_DEFAULT = 0.01
PREVIEW_BYTES = 8_000_000
"""Bytes of raw frames a second the preview takes at most (each BLOB costs the Pi's CPU)."""
PREVIEW_FPS = (1.0, 10.0)
STATS_PERIOD = 0.5
"""Seconds between updates of the frame's numbers and of a recording's progress."""
CROP_WAIT = 5.0
"""Seconds a driver has to send its first frame once the stream is on (beyond the
exposure)."""
BAD_FRAMES = 20
"""Frames in a row that cannot be shown before it is logged."""
BANDWIDTH = 90.0
"""ZWO's ``BandWidth`` while streaming: their default (40-50) halves the frame rate."""
KEEP = 100
"""Recordings listed (the files stay on the drive)."""
SAFETY_SECONDS = 2.0
"""A recording stops this many seconds of frames before the drive or the file is full."""
MAX_SECONDS = 3600.0
MAX_FRAMES = 1_000_000

_TICKS_PER_SECOND = 10_000_000
"""SER timestamps: 100 ns ticks."""


class VideoError(Exception):
    """A request the video cannot take now (not streaming, already recording)."""


class VideoUnavailableError(VideoError):
    """The main camera cannot stream video."""


@dataclass(frozen=True, slots=True)
class VideoSettings:
    exposure: float = EXPOSURE_DEFAULT
    gain: float | None = None
    """``None``: the camera's own until one is set here."""
    depth: int = 8
    region: Region | None = None
    """``None``: the whole sensor."""


@dataclass(slots=True)
class _Recording:
    id: str
    name: str
    path: Path
    place: VideoPlace
    started: datetime
    seconds: float | None
    frames: int | None
    exposure: float
    gain: float | None
    target: str | None
    filter: str | None
    frame_bytes: int
    token: str
    fps_samples: list[float]
    stopped: str | None = None
    """Why NOCS stopped it before its end: ``file_limit``, ``drive_full``."""
    measured: bool = False
    """``frame_bytes`` comes from the file's header."""
    written: int = 0
    size: int = 0


def fit_region(region: Region, sensor_width: int, sensor_height: int) -> Region:
    """``region`` as cameras read it: inside the sensor, at even coordinates, a width
    that is a multiple of 8 and an even height (ZWO's rules; Bayer sensors need the
    even start to keep their pattern)."""
    width = max(8, min(sensor_width, region.width) // 8 * 8)
    height = max(2, min(sensor_height, region.height) // 2 * 2)
    x = min(max(0, region.x), sensor_width - width) // 2 * 2
    y = min(max(0, region.y), sensor_height - height) // 2 * 2
    return Region(x, y, width, height)


def recording_name(
    started: datetime, target: str | None, exposure: float, gain: float | None
) -> str:
    """``20261121-213000-Jupiter-5ms-g300``: dashes only, since INDI's stream recorder
    replaces ``_D_``, ``_T_`` and ``_H_`` in names with the date and time."""
    parts = [started.astimezone(UTC).strftime("%Y%m%d-%H%M%S")]
    if target and (name := clean(target)):
        parts.append(name.replace("_", "-"))
    parts.append(f"{exposure * 1000:g}ms")
    if gain is not None:
        parts.append(f"g{gain:g}")
    return re.sub(r"-{2,}", "-", "-".join(parts))


def recorded_seconds(path: Path, header: SerHeader) -> float | None:
    """The time from the first frame to the last, from the SER file's trailer of
    timestamps (blocks); ``None`` without one."""
    frames = header.frames
    trailer = HEADER + frames * header.frame_bytes
    if frames < 2 or path.stat().st_size < trailer + 8 * frames:
        return None
    with path.open("rb") as f:
        f.seek(trailer)
        first = struct.unpack("<q", f.read(8))[0]
        f.seek(trailer + 8 * (frames - 1))
        last = struct.unpack("<q", f.read(8))[0]
    span = (last - first) / _TICKS_PER_SECOND
    if span <= 0:
        return None
    return span * frames / (frames - 1)


type ImageConnector = Callable[[str], Awaitable[IndiClient]]


class VideoService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        camera: Callable[[], Camera],
        release_images: Callable[[], Awaitable[None]],
        connect_images: ImageConnector,
        storage: StorageService,
        data_dir: Path,
        *,
        to_driver: Callable[[Path], str] = str,
        target: Callable[[], str | None] = lambda: None,
        filter: Callable[[], str | None] = lambda: None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._camera = camera
        """The main camera, on nocsd's connection; raises while it is not ready."""
        self._release_images = release_images
        self._connect_images = connect_images
        self._storage = storage
        self._to_driver = to_driver
        self._target = target
        self._filter = filter
        self._now = now
        self._file = data_dir / "video" / "recordings.json"
        self._settings = VideoSettings()
        self._job: str | None = None
        self._streaming = False
        self._restart = asyncio.Event()
        self._latest: tuple[bytes, int, int] | None = None
        self._arrived = asyncio.Event()
        self._jpeg: bytes | None = None
        self._seq = 0
        self._new_frame = asyncio.Event()
        self._rendered: Rendered | None = None
        self._frame_time: datetime | None = None
        self._fps: float | None = None
        self._recording: _Recording | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._recordings: list[dict[str, Json]] = []
        self._error: str | None = None
        self._published: dict[str, Json] | None = None

    async def start(self) -> None:
        """Read the recordings listed before (blocks on the card: in a thread)."""
        self._recordings = await anyio.to_thread.run_sync(self._load)
        self._publish()

    async def close(self) -> None:
        if self._watcher is not None:
            self._watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher

    # -- commands ---------------------------------------------------------

    @property
    def settings(self) -> VideoSettings:
        return self._settings

    @property
    def job(self) -> str | None:
        return self._job

    def start_stream(self) -> str:
        """Start streaming as a job that holds the main camera until it is cancelled."""
        if self._job is not None:
            raise VideoError("the video is already on")
        camera = self._camera()
        if not camera.can_stream:
            raise VideoUnavailableError(f"{camera.name} cannot stream video")
        self._error = None
        self._job = self._jobs.start(KIND, [Role.MAIN_CAMERA.value], self._run)
        self._publish()
        return self._job

    def stop_stream(self) -> None:
        if self._job is not None:
            self._jobs.cancel(self._job)

    async def configure(
        self,
        *,
        exposure: float | None = None,
        gain: float | None = None,
        depth: int | None = None,
        region: Region | None = None,
        full_frame: bool = False,
    ) -> None:
        """Change what the stream takes; while it streams, at once (a new region or depth
        restarts it). Refused while recording."""
        if self._recording is not None:
            raise VideoError("a recording is running: stop it first")
        camera = self._camera()
        settings = self._settings
        if exposure is not None:
            limits = camera.stream_exposure_range
            if exposure <= 0 or (limits is not None and not limits.min <= exposure <= limits.max):
                raise ValueError(f"exposure {exposure:g} s is outside what the camera takes")
            settings = replace(settings, exposure=exposure)
        if gain is not None:
            limits = camera.gain_range
            if limits is None:
                raise ValueError(f"{camera.name} has no gain")
            if not limits.min <= gain <= limits.max:
                raise ValueError(f"gain {gain:g} is outside {limits.min:g}..{limits.max:g}")
            settings = replace(settings, gain=gain)
        if depth is not None:
            if depth not in camera.video_depths:
                raise ValueError(f"{camera.name} cannot stream {depth}-bit video")
            settings = replace(settings, depth=depth)
        if full_frame:
            settings = replace(settings, region=None)
        elif region is not None:
            sensor = camera.sensor
            fitted = fit_region(region, sensor.width, sensor.height)
            full = fitted.width == sensor.width and fitted.height == sensor.height
            settings = replace(settings, region=None if full else fitted)
        previous, self._settings = self._settings, settings
        self._publish()
        if not self._streaming:
            return
        if settings.region != previous.region or settings.depth != previous.depth:
            self._restart.set()
            return
        if settings.exposure != previous.exposure:
            await camera.set_stream_exposure(settings.exposure)
        if settings.gain is not None and settings.gain != previous.gain:
            await camera.set_gain(settings.gain)

    async def record(self, *, seconds: float | None = None, frames: int | None = None) -> str:
        """Record the stream for ``seconds`` or ``frames`` to the storage destination;
        returns the recording's id at once."""
        if (seconds is None) == (frames is None):
            raise ValueError("a recording lasts seconds or frames")
        if seconds is not None and not 0 < seconds <= MAX_SECONDS:
            raise ValueError(f"a recording lasts up to {MAX_SECONDS:g} s")
        if frames is not None and not 0 < frames <= MAX_FRAMES:
            raise ValueError(f"a recording has up to {MAX_FRAMES} frames")
        if not self._streaming or self._rendered is None:
            raise VideoError("start the video first")
        if self._recording is not None:
            raise VideoError("already recording")
        camera = self._camera()
        rendered = self._rendered
        depth = self._settings.depth
        frame_bytes = rendered.frame_width * rendered.frame_height
        frame_bytes *= (3 if rendered.color and camera.bayer_pattern is None else 1) * (
            2 if depth == 16 else 1
        )
        fps = camera.stream_fps or 1 / self._settings.exposure
        count = frames if frames is not None else (seconds or 0) * fps
        expected = HEADER + int(frame_bytes * count)
        place = await anyio.to_thread.run_sync(self._storage.video_place, expected)
        if place.max_file is not None:
            expected = min(expected, place.max_file)
        token: str | None = None
        try:
            token = self._jobs.reserve(RECORDING_KIND, RECORDING_HOLDS)
            started = self._now()
            target = self._target()
            gain = camera.gain
            name = recording_name(started, target, self._settings.exposure, gain)
            path = place.directory / f"{name}.ser"
            n = 1
            while await anyio.to_thread.run_sync(path.exists):
                n += 1
                name = f"{recording_name(started, target, self._settings.exposure, gain)}-{n}"
                path = place.directory / f"{name}.ser"
            await camera.start_recording(
                Recording(self._to_driver(place.directory), name, seconds, frames)
            )
        except BaseException:
            if token is not None:
                self._jobs.release(token)
            self._storage.done_writing(place.destination)
            raise
        recording = _Recording(
            id=uuid.uuid4().hex[:12],
            name=name,
            path=path,
            place=place,
            started=started,
            seconds=seconds,
            frames=frames,
            exposure=self._settings.exposure,
            gain=gain,
            target=target,
            filter=self._filter(),
            frame_bytes=frame_bytes,
            token=token,
            fps_samples=[],
        )
        self._recording = recording
        self._publish()
        self._watcher = asyncio.get_running_loop().create_task(
            self._watch(camera, recording), name="video-recording"
        )
        return recording.id

    async def stop_recording(self) -> None:
        if self._recording is None:
            return
        await self._camera().stop_recording()

    async def next_frame(self, after: int) -> tuple[int, bytes] | None:
        """The newest preview once there is one newer than ``after``; waits for it
        (cancel the wait to give up)."""
        while self._seq <= after or self._jpeg is None:
            await self._new_frame.wait()
        return self._seq, self._jpeg

    def recording_file(self, recording_id: str) -> Path | None:
        entry = next((r for r in self._recordings if r.get("id") == recording_id), None)
        path = entry.get("file") if entry is not None else None
        return Path(path) if isinstance(path, str) else None

    async def delete_recording(self, recording_id: str) -> None:
        path = self.recording_file(recording_id)
        if path is None:
            raise KeyError(recording_id)
        await anyio.to_thread.run_sync(lambda: path.unlink(missing_ok=True))
        self._recordings = [r for r in self._recordings if r.get("id") != recording_id]
        await anyio.to_thread.run_sync(self._save)
        self._publish()

    # -- the stream ---------------------------------------------------------

    async def _run(self, context: JobContext) -> Json:
        camera = self._camera()
        # Frames are parsed once: on this connection, not also on Explore's.
        await self._release_images()
        images = await self._connect_images(camera.name)
        restore = _Restore.of(camera)
        stream = Camera(camera.client, camera.name, images)
        stop_watching = stream.watch_frames(self._on_frame, lambda: self._settings.exposure)
        try:
            while True:
                self._restart.clear()
                await self._setup(camera)
                self._streaming = True
                self._publish()
                context.progress(None, "streaming")
                tasks = [
                    asyncio.get_running_loop().create_task(self._previews(camera)),
                    asyncio.get_running_loop().create_task(self._stats(camera)),
                ]
                try:
                    await self._restart.wait()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                self._streaming = False
                await camera.stop_stream()
        except DeviceError as e:
            self._error = str(e)
            raise
        finally:
            stop_watching()
            self._streaming = False
            await self._end(camera, images, restore)
        return None

    async def _setup(self, camera: Camera) -> None:
        if self._settings.depth not in (depths := camera.video_depths):
            self._settings = replace(self._settings, depth=depths[0])
        settings = self._settings
        if camera.binning != (1, 1):
            await camera.set_binning(1)
        # ZWO's SDK reads the whole sensor again after a change of format or speed: the
        # region goes last, right before the stream.
        if (bandwidth := camera.control("BandWidth")) is not None:
            wanted = min(max(BANDWIDTH, bandwidth.min), bandwidth.max)
            if bandwidth.value != wanted:
                await camera.set_control("BandWidth", wanted)
        if (speed := camera.control("HighSpeedMode")) is not None and speed.value != speed.max:
            await camera.set_control("HighSpeedMode", speed.max)
        await camera.set_video_depth(settings.depth)
        await camera.set_stream_exposure(settings.exposure)
        if settings.gain is not None:
            await camera.set_gain(settings.gain)
        await camera.set_stream_encoder("RAW")
        sensor = camera.sensor
        region = settings.region or Region(0, 0, sensor.width, sensor.height)
        frame = region.width * region.height * (2 if settings.depth == 16 else 1)
        low, high = PREVIEW_FPS
        await camera.set_preview_rate(round(min(high, max(low, PREVIEW_BYTES / frame)), 1))
        await camera.set_region(settings.region)
        self._latest = None
        self._arrived.clear()
        self._rendered = None
        self._jpeg = None
        await camera.start_stream()
        if settings.region is not None:
            await self._crop(camera, settings.region)

    async def _crop(self, camera: Camera, region: Region) -> None:
        """Have the stream manager cut the region out when the driver streams the whole
        sensor anyway: the first frame's size tells."""
        try:
            await asyncio.wait_for(self._arrived.wait(), CROP_WAIT + self._settings.exposure)
        except TimeoutError:
            log.warning(
                "%s sent no video frame %g s after the stream started", camera.name, CROP_WAIT
            )
            return
        latest, self._latest = self._latest, None
        self._arrived.clear()
        if latest is None:
            return
        sensor = camera.sensor
        area = sensor.width * sensor.height
        size = len(latest[0])
        if area != region.width * region.height and size % area == 0 and size // area <= 6:
            # The cut is clamped to CCD_FRAME, which then has to be the whole sensor.
            log.info("%s streams its whole sensor: the stream manager cuts the region", camera.name)
            await camera.set_region(None)
            await camera.set_stream_frame(region)

    def _on_frame(self, frame: Frame) -> None:
        if frame.format != ".stream":
            return
        try:
            size = self._camera().stream_frame
        except (DeviceError, KeyError) as e:
            log.debug("a video frame without its size: %s", e)
            return
        if size is None:
            return
        self._latest = (frame.data, size.width, size.height)
        self._arrived.set()

    async def _previews(self, camera: Camera) -> None:
        """Turn the newest frame into a preview, skipping those that came meanwhile."""
        bayer = camera.bayer_pattern
        failures = 0
        while True:
            await self._arrived.wait()
            self._arrived.clear()
            latest, self._latest = self._latest, None
            if latest is None:
                continue
            data, width, height = latest
            try:
                rendered = await anyio.to_thread.run_sync(render, data, width, height, bayer)
            except FrameError as e:
                # Frames of the size before a change can still be on their way.
                failures += 1
                if failures == BAD_FRAMES:
                    log.warning("video frames cannot be shown: %s", e)
                continue
            failures = 0
            self._rendered = rendered
            self._frame_time = self._now()
            self._jpeg = rendered.jpeg
            self._seq += 1
            event, self._new_frame = self._new_frame, asyncio.Event()
            event.set()

    async def _stats(self, camera: Camera) -> None:
        while True:
            self._fps = camera.stream_fps
            self._publish()
            await asyncio.sleep(STATS_PERIOD)

    async def _end(self, camera: Camera, images: IndiClient, restore: _Restore) -> None:
        """Leave the camera as it was before the video, whatever happened; never raises."""
        for step in (camera.stop_recording, camera.stop_stream, lambda: restore.apply(camera)):
            try:
                await asyncio.wait_for(step(), 30)
            except (DeviceError, TimeoutError, ConnectionError, KeyError, ValueError) as e:
                log.warning("leaving the video: %s", e)
        with contextlib.suppress(Exception):
            await images.close()
        self._job = None
        self._fps = None
        self._rendered = None
        self._jpeg = None
        self._publish()

    # -- recordings ---------------------------------------------------------

    async def _watch(self, camera: Camera, recording: _Recording) -> None:
        """Follow a recording to its end, stopping it before the drive or the file is
        full, then list it."""
        loop = asyncio.get_running_loop()
        began = loop.time()
        try:
            while True:
                await asyncio.sleep(STATS_PERIOD)
                if not camera.recording and loop.time() - began > 1.0:
                    break
                if (fps := camera.stream_fps) is not None:
                    recording.fps_samples.append(fps)
                await self._check_room(camera, recording)
                self._publish()
        except (DeviceError, ConnectionError, KeyError) as e:
            log.warning("recording %s: %s", recording.name, e)
        finally:
            # The driver writes the frame count into the header as it closes the file.
            await asyncio.sleep(1.0)
            entry = await anyio.to_thread.run_sync(self._finished, recording)
            self._jobs.release(recording.token)
            self._storage.done_writing(recording.place.destination)
            self._recording = None
            if entry is not None:
                self._recordings = [entry, *self._recordings][:KEEP]
                await anyio.to_thread.run_sync(self._save)
            self._publish()

    async def _check_room(self, camera: Camera, recording: _Recording) -> None:
        path = recording.path

        def measure() -> tuple[int, int, SerHeader | None]:
            size = path.stat().st_size if path.exists() else 0
            header: SerHeader | None = None
            if size >= HEADER and not recording.measured:
                with contextlib.suppress(SerError, OSError):
                    header = read_header(path)
            return size, self._storage.free(path.parent), header

        size, free, header = await anyio.to_thread.run_sync(measure)
        if header is not None and header.frame_bytes > 0:
            # The file says what a frame takes: the estimate was only that.
            recording.frame_bytes = header.frame_bytes
            recording.measured = True
        recording.size = size
        recording.written = max(0, (size - HEADER) // recording.frame_bytes)
        fps = camera.stream_fps or 1 / recording.exposure
        margin = int(recording.frame_bytes * fps * SAFETY_SECONDS)
        limit = recording.place.max_file
        reason: str | None = None
        if limit is not None and size + margin >= limit:
            reason = "file_limit"
        elif free <= margin:
            reason = "drive_full"
        if reason is not None and recording.stopped is None:
            recording.stopped = reason
            log.warning("stopping recording %s: %s", recording.name, reason)
            await camera.stop_recording()

    def _finished(self, recording: _Recording) -> dict[str, Json] | None:
        """The listed entry of a recording that ended (blocks)."""
        path = recording.path
        if not path.exists():
            log.warning("recording %s left no file at %s", recording.name, path)
            self._error = f"the recording left no file at {path}"
            return None
        header: SerHeader | None
        try:
            header = read_header(path)
        except (SerError, OSError) as e:
            log.warning("recording %s: %s", recording.name, e)
            header = None
        frames = header.frames if header is not None else 0
        if header is not None and frames == 0:
            frames = frames_written(path, header)
        seconds: float | None = None
        if header is not None:
            with contextlib.suppress(OSError, struct.error):
                seconds = recorded_seconds(path, header)
        if seconds is None:
            seconds = max(0.0, (self._now() - recording.started).total_seconds() - 1.0)
        samples = recording.fps_samples
        camera_fps = sum(samples) / len(samples) if samples else None
        fps = frames / seconds if seconds > 0 else None
        dropped: int | None = None
        if camera_fps is not None and seconds > 0:
            dropped = max(0, round(camera_fps * seconds) - frames)
        destination = recording.place.destination
        return {
            "id": recording.id,
            "name": f"{recording.name}.ser",
            "file": str(path),
            "path": str(recording.place.relative / f"{recording.name}.ser"),
            "destination": destination.id,
            "destination_label": destination.label,
            "size": path.stat().st_size,
            "frames": frames,
            "width": header.width if header else None,
            "height": header.height if header else None,
            "depth": header.depth if header else None,
            "color": header.color if header else None,
            "seconds": round(seconds, 3),
            "fps": round(fps, 2) if fps is not None else None,
            "camera_fps": round(camera_fps, 2) if camera_fps is not None else None,
            "dropped": dropped,
            "exposure": recording.exposure,
            "gain": recording.gain,
            "target": recording.target,
            "filter": recording.filter,
            "started": recording.started.astimezone(UTC).isoformat(timespec="seconds"),
            "stopped": recording.stopped,
        }

    # -- state --------------------------------------------------------------

    def _publish(self) -> None:
        settings = self._settings
        region = settings.region
        rendered = self._rendered
        recording = self._recording
        summary: dict[str, Json] = {
            "job": self._job,
            "streaming": self._streaming,
            "exposure": settings.exposure,
            "gain": settings.gain,
            "depth": settings.depth,
            "region": (
                {"x": region.x, "y": region.y, "width": region.width, "height": region.height}
                if region is not None
                else None
            ),
            "fps": round(self._fps, 1) if self._fps is not None else None,
            "frame": (
                {
                    "seq": self._seq,
                    "width": rendered.width,
                    "height": rendered.height,
                    "frame_width": rendered.frame_width,
                    "frame_height": rendered.frame_height,
                    "depth": rendered.depth,
                    "color": rendered.color,
                    "histogram": list[Json](rendered.histogram),
                    "saturated": rendered.saturated,
                    "sharpness": rendered.sharpness,
                    "time": (self._frame_time or self._now()).isoformat(timespec="seconds"),
                }
                if rendered is not None
                else None
            ),
            "recording": (
                {
                    "id": recording.id,
                    "name": f"{recording.name}.ser",
                    "path": str(recording.place.relative / f"{recording.name}.ser"),
                    "destination_label": recording.place.destination.label,
                    "started": recording.started.astimezone(UTC).isoformat(timespec="seconds"),
                    "seconds": recording.seconds,
                    "frames": recording.frames,
                    "written": recording.written,
                    "size": recording.size,
                    "max_file": recording.place.max_file,
                    "stopping": recording.stopped,
                }
                if recording is not None
                else None
            ),
            "recordings": list[Json](self._recordings),
            "error": self._error,
        }
        previous = self._published
        if previous is None:
            self._store.set(ROOT, summary)
        else:
            changed = {k: v for k, v in summary.items() if previous.get(k) != v}
            if not changed:
                return
            with self._store.transaction():
                for key, value in changed.items():
                    self._store.set((*ROOT, key), value)
        self._published = summary

    def _load(self) -> list[dict[str, Json]]:
        try:
            data = json.loads(self._file.read_text())
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            log.warning("cannot read %s: %s", self._file, e)
            return []
        if not isinstance(data, list):
            return []
        kept: list[dict[str, Json]] = []
        for entry in cast(list[object], data):
            if isinstance(entry, dict):
                fields = cast(dict[str, Json], entry)
                file = fields.get("file")
                if isinstance(file, str) and os.path.exists(file):
                    kept.append(fields)
        return kept

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(self._file, json.dumps(self._recordings, indent=1))


@dataclass(frozen=True, slots=True)
class _Restore:
    """What the video changes on the camera and puts back at its end."""

    region: Region
    binning: int
    controls: dict[str, float]

    @classmethod
    def of(cls, camera: Camera) -> _Restore:
        controls: dict[str, float] = {}
        for name in ("BandWidth", "HighSpeedMode"):
            if (element := camera.control(name)) is not None:
                controls[name] = element.value
        return cls(camera.region, camera.binning[0], controls)

    async def apply(self, camera: Camera) -> None:
        sensor = camera.sensor
        stream = camera.stream_frame
        if stream is not None and (stream.width, stream.height) != (sensor.width, sensor.height):
            with contextlib.suppress(DeviceError):
                await camera.set_region(None)
                await camera.set_stream_frame(Region(0, 0, sensor.width, sensor.height))
        await camera.set_region(self.region)
        if camera.binning[0] != self.binning:
            await camera.set_binning(self.binning)
        for name, value in self.controls.items():
            element = camera.control(name)
            if element is not None and element.value != value:
                await camera.set_control(name, value)
