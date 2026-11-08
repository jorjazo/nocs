"""Live stacking in nocsd: which frames go to which stack, and the state (ADR 0040).

The capture service offers every light of the main camera that got a preview, from
Live view and sequences alike, while stacking is on. Frames wait in a slot of one:
a newer frame replaces one still waiting (counted as skipped), so stacking never
holds up a capture or falls behind. One task takes them in turn to the imaging
worker, which holds the pixels.

A stack is for one setup: camera, frame size, binning, gain, offset, exposure,
filter and target. A frame of another setup ends the stack and starts a new one;
mono cameras keep a stack per filter and go back to it (LRGB nights), colour ones
keep only the current one. Three frames in a row that do not register start a new
stack too (the mount went elsewhere), as does *New stack*.

A new stack first gets its calibration: the library's darks (or bias) and flats
for its setup, built into masters by the worker (once; they are cached).

An unsaved frame (Live view's loop) is hard-linked aside, as the capture service
deletes its file when the next frame arrives; the link is deleted once stacked.

State under ``("stack",)``: ``on``, ``status``, the current stack's counts, setup,
calibration, the last frame's outcome and the preview's URL, and the look.
Settings (``on`` and the look) persist in ``<config dir>/stacking.json``.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import logging
import os
import shutil
import uuid
from collections import OrderedDict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import anyio
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from pydantic import ValidationError

from nocs.calibration.library import Light, Setup
from nocs.equipment.profiles import write_atomic
from nocs.stacking import calibrate
from nocs.stacking.calibrate import MasterSpec
from nocs.stacking.frames import Offered
from nocs.stacking.masters import Calibration, Kind, Master
from nocs.stacking.settings import StackLook, StackSettings
from nocs.stacking.stack import Added, Look, Rendered, StackLostError
from nocs.state import Json, StateStore
from nocs.storage import FrameRow, FrameUnavailableError

log = logging.getLogger(__name__)

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline

ROOT = ("stack",)
SETTINGS_FILE = "stacking.json"
MISSES = 3
"""Frames in a row that do not register before a new stack starts."""
STACKS = 4
"""Stacks kept for a mono camera, one per filter."""


class Worker(Protocol):
    """The imaging worker's stacking calls (``ImageWorker``)."""

    previews_dir: Path

    async def stack_add(
        self,
        stack_id: str,
        fits_path: str,
        bayer: str | None,
        *,
        new: bool,
        stars: int | None,
        hfr: float | None,
        look: Look,
        calibration: Calibration | None = None,
    ) -> Added: ...
    async def stack_render(self, stack_id: str, look: Look) -> Rendered: ...
    async def stack_drop(self, stack_id: str) -> None: ...
    async def build_master(
        self,
        path: str,
        kind: Kind,
        frames: list[str],
        bayer: str | None,
        subtract: str | None = None,
    ) -> Master: ...


class Library(Protocol):
    """The frame catalog (``StorageService``); blocking, called from threads."""

    def calibration_frames(self, cameras: list[str]) -> list[FrameRow]: ...
    def frame_file(self, frame_id: int) -> tuple[FrameRow, Path]: ...


type Key = tuple[
    str,
    int | None,
    int | None,
    int | None,
    float | None,
    float | None,
    float,
    str | None,
    str | None,
]


@dataclass(slots=True)
class LiveStack:
    """nocsd's record of a stack the worker holds."""

    id: str
    key: Key
    offered: Offered
    width: int | None
    height: int | None
    started: datetime
    colour: bool
    calibration: Calibration = field(default_factory=lambda: Calibration(cosmetic=True))
    notes: list[str] = field(default_factory=list[str])
    used: dict[str, Json] = field(default_factory=dict[str, Json])
    """What the calibration is made of, for the state (``StackCalibration``)."""
    created: bool = False
    """The worker has it (its first frame went there)."""
    frames: int = 0
    rejected: int = 0
    skipped: int = 0
    exposure: float = 0.0
    misses: int = 0
    last: dict[str, Json] | None = None
    preview: dict[str, Json] | None = None
    ids: list[int] = field(default_factory=list[int])
    """Catalog ids of the saved frames in it."""


class LiveStackService:
    def __init__(
        self,
        store: StateStore,
        worker: Worker,
        library: Callable[[], Library],
        config_dir: Path,
        data_dir: Path,
    ) -> None:
        self._store = store
        self._worker = worker
        self._library = library
        self._settings_path = config_dir / SETTINGS_FILE
        self._masters = data_dir / "masters"
        self._links = data_dir / "stacking"
        self.settings = StackSettings()
        self._stacks: OrderedDict[Key, LiveStack] = OrderedDict()
        self._current: LiveStack | None = None
        self._pending: Offered | None = None
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._status = "idle"
        self._message: str | None = None
        self._building: dict[str, Json] | None = None
        self._error: str | None = None
        self._new = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._early_skips: dict[Key, int] = {}
        """Frames skipped while the stack of their setup was still being started."""
        self._publish()

    async def start(self) -> None:
        """Read the settings, and delete links a stopped nocsd left behind (each a whole
        frame on the drive); in a thread, as both touch the microSD."""
        self.settings = await anyio.to_thread.run_sync(self._load)
        await anyio.to_thread.run_sync(self._clear_links)
        self._publish()

    @property
    def on(self) -> bool:
        return self.settings.on

    async def set_on(self, on: bool) -> None:
        settings = self.settings.model_copy(update={"on": on})
        await anyio.to_thread.run_sync(self._save_settings, settings)
        self.settings = settings
        if on:
            self._status, self._message, self._error = "idle", None, None
        else:
            await self._end_all()
        self._publish()

    async def set_look(self, look: StackLook) -> None:
        """Keep the look and show the current stack with it at once."""
        settings = self.settings.model_copy(update={"look": look})
        await anyio.to_thread.run_sync(self._save_settings, settings)
        self.settings = settings
        stack = self._current
        if stack is not None and stack.created and stack.frames:
            try:
                rendered = await self._worker.stack_render(stack.id, _look(look))
            except StackLostError:
                self._lost(stack)
            else:
                stack.preview = self._preview(rendered)
        self._publish()

    async def reset(self) -> None:
        """Start a new stack with the next frame."""
        await self._end_all()
        self._publish()

    async def offer(self, frame: Offered) -> None:
        """A new light; returns at once. ``frame.owned``: the caller deletes the file
        soon, so a link to it is taken here (in a thread: ext4 can stall on the Pi)."""
        if not self.on:
            return
        if frame.owned:
            try:
                link = await anyio.to_thread.run_sync(self._link, frame.path)
            except OSError as e:
                log.warning("live stack: could not keep %s: %s", frame.path.name, e)
                return
            frame = replace(frame, path=link)
        replaced, self._pending = self._pending, frame
        if replaced is not None:
            skipped = next(
                (s for s in self._stacks.values() if _same_setup(s.offered, replaced)), None
            )
            if skipped is not None:
                skipped.skipped += 1
            else:  # its stack is still being started: it counts there once it exists
                setup = _key(replaced, None, None)
                self._early_skips[setup] = self._early_skips.get(setup, 0) + 1
            # Not on the capture's path: an unlink can wait seconds on the Pi's microSD.
            self._background(self._discard(replaced))
        self._idle.clear()
        self._wake.set()

    async def run(self) -> None:
        """Take offered frames to the worker, one at a time, until cancelled."""
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                frame, self._pending = self._pending, None
                if frame is None:
                    self._idle.set()
                    continue
                try:
                    await self._take(frame)
                except asyncio.CancelledError:
                    raise
                except _AbandonedError:
                    pass  # the stack was ended while it got ready: the frame goes with it
                except Exception as e:
                    log.exception("live stack: %s", e)
                    self._status, self._error = "failed", str(e)
                    if self._current is not None:
                        failed = self._current
                        self._stacks.pop(failed.key, None)
                        self._current = None
                        if failed.created:
                            self._background(self._drop(failed.id))
                finally:
                    await self._discard(frame)
                    self._publish()
                if self._pending is None:
                    self._idle.set()
                else:
                    self._wake.set()
        finally:
            pending, self._pending = self._pending, None
            if pending is not None:
                self._background(self._discard(pending))

    async def idle(self) -> None:
        """Wait until every offered frame has been dealt with (tests)."""
        await self._idle.wait()

    async def _take(self, frame: Offered) -> None:
        if not self.on:
            return
        width, height = await anyio.to_thread.run_sync(_dimensions, frame.path)
        key = _key(frame, width, height)
        stack = self._stacks.get(key)
        if self._new or stack is None:
            self._new = False
            if stack is not None:
                await self._end(stack)
            if frame.bayer is not None or (self._current is not None and self._current.colour):
                await self._drop_all()  # colour: only the current stack is kept
            stack = await self._start(frame, key, width, height)
        self._stacks.move_to_end(key)
        self._current = stack
        await self._add(stack, frame, retry=True)

    async def _add(self, stack: LiveStack, frame: Offered, *, retry: bool) -> None:
        self._status, self._message, self._error = "stacking", None, None
        self._publish()
        try:
            added = await self._worker.stack_add(
                stack.id,
                str(frame.path),
                frame.bayer,
                new=not stack.created,
                stars=frame.stars,
                hfr=frame.hfr,
                look=_look(self.settings.look),
                calibration=stack.calibration,
            )
        except StackLostError:
            if not retry:
                raise
            self._lost(stack)
            stack = await self._start(frame, stack.key, stack.width, stack.height)
            await self._add(stack, frame, retry=False)
            return
        stack.created = True
        if self._stacks.get(stack.key) is not stack:
            # Ended (New stack, switched off) while the worker added the frame: the
            # worker holds it still, and only this call knows.
            await self._drop(stack.id)
            return
        stack.frames, stack.rejected = added.frames, added.rejected
        stack.last = _outcome(added, frame)
        if added.accepted:
            stack.misses = 0
            stack.exposure += frame.exposure
            if frame.frame_id is not None:
                stack.ids.append(frame.frame_id)
            if added.preview is not None:
                stack.preview = self._preview(added.preview)
        elif added.cause == "registration":
            stack.misses += 1
            if stack.misses >= MISSES and retry:
                log.info("live stack: %d frames did not register; a new stack", MISSES)
                await self._end(stack)
                stack = await self._start(frame, stack.key, stack.width, stack.height)
                stack.notes.append(f"started again: {MISSES} frames did not register")
                self._current = stack
                await self._add(stack, frame, retry=False)
                return
        self._status = "stacking"

    async def _start(
        self, frame: Offered, key: Key, width: int | None, height: int | None
    ) -> LiveStack:
        stack = LiveStack(
            id=uuid.uuid4().hex,
            key=key,
            offered=frame,
            width=width,
            height=height,
            started=frame.taken,
            colour=frame.bayer is not None,
        )
        stack.skipped = self._early_skips.pop(_key(frame, None, None), 0)
        self._stacks[key] = stack
        self._current = stack
        while len(self._stacks) > STACKS:
            oldest = next(iter(self._stacks.values()))
            await self._end(oldest)
        self._status, self._message = "preparing", "looking for darks and flats"
        self._publish()
        stack.calibration, stack.notes, stack.used = await self._calibration(frame, width, height)
        if self._stacks.get(key) is not stack:
            raise _AbandonedError  # ended (New stack, switched off) while its masters were built
        return stack

    async def _calibration(
        self, frame: Offered, width: int | None, height: int | None
    ) -> tuple[Calibration, list[str], dict[str, Json]]:
        """The masters for a stack of frames like ``frame``, built if needed."""
        light = Light(
            Setup(frame.camera, width, height, frame.binning, frame.gain, frame.offset),
            frame.filter,
            frame.exposure,
            frame.temperature,
            frame.night,
            rotation=frame.rotation,
        )
        try:
            library = self._library()
            rows = await anyio.to_thread.run_sync(library.calibration_frames, [frame.camera])
        except Exception as e:  # no catalog (no drive), or it failed
            log.warning("live stack: no calibration library: %s", e)
            return Calibration(cosmetic=True), [f"no calibration library: {e}"], _unused()
        found = calibrate.plan(light, rows)
        notes = list(found.notes)
        used = _unused()
        used["flats_unused"] = found.flats_unused
        counts: dict[MasterSpec, int] = {}

        async def master(spec: MasterSpec | None, subtract: str | None = None) -> str | None:
            if spec is None:
                return None
            self._message = f"building the {spec.kind} master ({len(spec.frames)} frames)"
            self._building = {"kind": spec.kind, "frames": len(spec.frames)}
            self._publish()
            try:
                built = await self._build(library, spec, frame.bayer, subtract)
            except Exception as e:  # a broken file, a full drive: stack without it
                log.warning("live stack: no %s master: %s", spec.kind, e)
                notes.append(f"no {spec.kind} master: {e}")
                return None
            if built is None:
                return None
            path, count = built
            counts[spec] = count
            return path

        dark = await master(found.dark)
        bias = found.dark is not None and found.dark.kind == "bias"
        flat: str | None = None
        if found.flat is not None:
            offset = await master(found.flat_offset)
            if offset is None:
                notes.append("flats not used: no master of their bias or dark flats")
                used["flat_failed"] = True
            else:
                flat = await master(found.flat, offset)
                used["flat_failed"] = flat is None
        if dark is not None and found.dark is not None:
            used["dark_kind"] = found.dark.kind
            used["dark_frames"] = counts[found.dark]
        elif found.dark is not None:
            used["dark_failed"] = True  # found, but none of them could be read or used
        if flat is not None and found.flat is not None:
            used["flat_frames"] = counts[found.flat]
        self._message = None
        self._building = None
        return Calibration(dark=dark, flat=flat, cosmetic=True, bias=bias), notes, used

    async def _build(
        self, library: Library, spec: MasterSpec, bayer: str | None, subtract: str | None
    ) -> tuple[str, int] | None:
        """The master's path and its frames, or None when none of them is at hand."""
        files: list[str] = []
        ids: list[int] = []
        for frame_id in spec.frames:
            try:
                _, path = await anyio.to_thread.run_sync(library.frame_file, frame_id)
            except (KeyError, OSError, FrameUnavailableError) as e:  # unplugged, deleted
                log.debug("live stack: frame %d unavailable: %s", frame_id, e)
                continue
            files.append(str(path))
            ids.append(frame_id)
        if not files:
            return None
        available = MasterSpec(spec.kind, tuple(ids))
        target = self._masters / available.file_name(bayer, subtract)
        await self._worker.build_master(str(target), spec.kind, files, bayer, subtract)
        return str(target), len(files)

    async def _end(self, stack: LiveStack) -> None:
        """Forget a stack (and free the worker's memory)."""
        self._stacks.pop(stack.key, None)
        if self._current is stack:
            self._current = None
        if stack.created:
            await self._drop(stack.id)

    async def _drop(self, stack_id: str) -> None:
        """Free a stack in the worker; a worker that cannot answer holds nothing."""
        with contextlib.suppress(Exception):
            await self._worker.stack_drop(stack_id)

    async def _end_all(self) -> None:
        """End every stack; the next frame starts a new one."""
        self._new = True
        await self._drop_all()

    async def _drop_all(self) -> None:
        for stack in list(self._stacks.values()):
            await self._end(stack)

    def _lost(self, stack: LiveStack) -> None:
        log.warning("live stack: the worker lost stack %s (restarted?)", stack.id)
        self._stacks.pop(stack.key, None)
        if self._current is stack:
            self._current = None

    def _preview(self, rendered: Rendered) -> dict[str, Json]:
        return {
            "url": f"/api/previews/{Path(rendered.path).name}",
            "width": rendered.width,
            "height": rendered.height,
        }

    def _link(self, path: Path) -> Path:
        self._links.mkdir(parents=True, exist_ok=True)
        link = self._links / f"{uuid.uuid4().hex}{path.suffix}"
        try:
            os.link(path, link)
        except OSError as e:
            if e.errno not in (errno.EXDEV, errno.EPERM, errno.EMLINK):
                raise
            shutil.copyfile(path, link)  # another filesystem
        return link

    async def _discard(self, frame: Offered) -> None:
        """Delete a frame's own link; never raises (the stacking goes on)."""
        if not frame.owned:
            return
        try:
            await anyio.to_thread.run_sync(lambda: frame.path.unlink(missing_ok=True))
        except OSError as e:
            log.warning("live stack: could not delete %s: %s", frame.path, e)

    def _background(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)  # kept until done
        task.add_done_callback(self._tasks.discard)

    def _clear_links(self) -> None:
        if self._links.is_dir():
            for path in self._links.iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)

    def _load(self) -> StackSettings:
        try:
            return StackSettings.model_validate_json(self._settings_path.read_bytes())
        except FileNotFoundError:
            return StackSettings()
        except (OSError, ValidationError) as e:
            log.warning("ignoring unreadable %s: %s", self._settings_path, e)
            return StackSettings()

    def _save_settings(self, settings: StackSettings) -> None:
        write_atomic(self._settings_path, settings.model_dump_json(indent=2) + "\n")

    def _publish(self) -> None:
        stack = self._current
        current: Json = None
        if stack is not None:
            frame = stack.offered
            current = {
                "id": stack.id,
                "started": stack.started.isoformat(timespec="seconds"),
                "frames": stack.frames,
                "rejected": stack.rejected,
                "skipped": stack.skipped,
                "exposure": round(stack.exposure, 3),
                "camera": frame.camera,
                "target": frame.target,
                "filter": frame.filter,
                "setup": {
                    "exposure": frame.exposure,
                    "gain": frame.gain,
                    "offset": frame.offset,
                    "binning": frame.binning,
                    "width": stack.width,
                    "height": stack.height,
                    "colour": stack.colour,
                },
                "calibration": {
                    "dark": stack.calibration.dark is not None,
                    "flat": stack.calibration.flat is not None,
                    "cosmetic": stack.calibration.dark is None,
                    "notes": list[Json](stack.notes),
                    **(stack.used or _unused()),
                },
                "last": stack.last,
                "preview": stack.preview,
            }
        self._store.set(
            ROOT,
            {
                "on": self.on,
                "status": self._status if self.on else "off",
                "message": self._message,
                "building": self._building,
                "error": self._error,
                "look": self.settings.look.model_dump(),
                "current": current,
                "stacks": len(self._stacks),
            },
        )


def _unused() -> dict[str, Json]:
    return {
        "dark_kind": None,
        "dark_frames": 0,
        "dark_failed": False,
        "flat_frames": 0,
        "flats_unused": False,
        "flat_failed": False,
    }


class _AbandonedError(Exception):
    """The stack a frame was starting was ended meanwhile."""


def _same_setup(a: Offered, b: Offered) -> bool:
    return _key(a, None, None) == _key(b, None, None)


def _look(look: StackLook) -> Look:
    return Look(look.background, look.shadows, look.saturation, look.linked)


def _key(frame: Offered, width: int | None, height: int | None) -> Key:
    return (
        frame.camera,
        width,
        height,
        frame.binning,
        frame.gain,
        frame.offset,
        frame.exposure,
        frame.filter,
        frame.target,
    )


def _dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        header = _fits.getheader(path)
        return int(header["NAXIS1"]), int(header["NAXIS2"])
    except (OSError, KeyError, ValueError):
        return None, None


def _outcome(added: Added, frame: Offered) -> dict[str, Json]:
    return {
        "accepted": added.accepted,
        "reason": added.reason,
        "cause": added.cause,
        "shift": list[Json](added.shift) if added.shift is not None else None,
        "rotation": added.rotation,
        "stars": added.stars,
        "rms": added.rms,
        "clipped": added.clipped,
        "hot_pixels": added.hot_pixels,
        "seconds": added.seconds,
        "time": frame.taken.isoformat(timespec="seconds"),
        "frame_id": frame.frame_id,
    }
