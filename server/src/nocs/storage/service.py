"""Where frames are saved, how they are named, and the catalog of them (ADR 0013).

State layout under ``("storage",)``::

    {destinations, unmounted, choice, destination, error, target, template, catalog_error}

The choice (automatic or a destination), the target name and the file name
template are kept in ``<config dir>/storage.json``. Saving and catalog queries
block: they run in threads, never on the event loop.

Where nocs-system mounts and ejects drives (ADR 0027), a USB drive is mounted as
soon as it is plugged in, and ejecting one waits for the frame being saved to it;
``unmounted`` lists the drives plugged in but not mounted, with the reason.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import sqlite3
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import anyio
import zipstream  # pyright: ignore[reportMissingTypeStubs]
from pydantic import BaseModel, ConfigDict, ValidationError

from nocs import __version__
from nocs.equipment.profiles import Optics, Site, write_atomic
from nocs.state import Json, StateStore
from nocs.state import Path as StatePath
from nocs.storage import layout
from nocs.storage.catalog import (
    Catalog,
    CatalogError,
    FocusRun,
    FrameFilter,
    FrameRow,
    NewFrame,
    NightRow,
    Session,
    SessionEvent,
    TemperatureSample,
)
from nocs.storage.fits import Card, FitsError, Header, place
from nocs.storage.volumes import (
    INTERNAL,
    SEARCH,
    Attached,
    Destination,
    SystemPaths,
    Volumes,
    unmounted_usb,
)

log = logging.getLogger(__name__)

# zipstream-ng has no type information; used only through this untyped handle.
_zipstream: Any = zipstream

ROOT: StatePath = ("storage",)
AUTO = "auto"
RESERVE = 1 << 30
"""Bytes left free on any destination after a frame, so the OS disk never fills up."""
POLL_SECONDS = 5.0
OWNED_KEYWORDS = frozenset({"OBJECT", "SWCREATE"})
"""Header keywords NOCS always writes; others are added only when the driver did not."""


class StorageError(Exception):
    pass


class FrameUnavailableError(Exception):
    """The frame's drive is not mounted."""


class DriveBusyError(StorageError):
    """Ejecting the drive now would lose a frame, or interrupt running work."""


class EjectUnavailableError(StorageError):
    """NOCS cannot eject drives on this computer."""


class SystemHelper(Protocol):
    """What storage needs from nocs-system: ``nocs.services.system.SystemService``."""

    def offers(self, op: str) -> bool: ...

    async def perform(self, op: str, args: dict[str, object]) -> dict[str, object]: ...


class AutoLock(BaseModel):
    """In automatic mode, the external drive a night started saving to."""

    night: date
    volume: str
    label: str


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    destination: str = AUTO
    destination_label: str | None = None
    target: str | None = None
    template: str = layout.DEFAULT_TEMPLATE
    auto_lock: AutoLock | None = None


@dataclass(frozen=True, slots=True)
class FrameFacts:
    """What the capture service knows about a frame when it hands it over."""

    source: Path
    frame_type: str
    exposure: float
    arrived: datetime
    camera: str
    gain: float | None
    offset: float | None
    binning: int | None
    temperature: float | None
    cooler_target: float | None
    filter: str | None
    profile: str | None
    site: Site | None
    optics: Optics | None
    clock_correction: float = 0.0
    """Seconds to add to the driver's DATE-OBS: the system clock is off (nocs.clock)."""
    ambient: float | None = None
    """°C, from the weather role (ADR 0017)."""
    humidity: float | None = None
    dew_point: float | None = None
    target: str | None = None
    """A light frame's object, instead of the configured target (a sequence's frames)."""


@dataclass(frozen=True, slots=True)
class SavedFrame:
    id: int
    path: Path
    relative: PurePosixPath
    """Below ``<destination>/NOCS/``."""
    destination: str
    size: int
    started: datetime


@dataclass(frozen=True, slots=True)
class Located:
    row: FrameRow
    path: Path | None
    """Where the file is now; ``None`` while its drive is not mounted."""


class StorageService:
    def __init__(
        self,
        store: StateStore,
        config_dir: Path,
        data_dir: Path,
        internal_dir: Path,
        longitude: Callable[[], float | None] = lambda: None,
        paths: SystemPaths | None = None,
        search: tuple[Path, ...] = SEARCH,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        helper: SystemHelper | None = None,
        busy: Callable[[], list[str]] = list,
    ) -> None:
        self._store = store
        self._helper = helper
        self._busy = busy
        """Kinds of the running jobs, which ejecting a drive would disturb."""
        self._writing = Counter[str]()
        """Volume id → frames being saved to it."""
        self._ejecting: set[str] = set()
        self._unmounted: list[Attached] = []
        self._present: set[tuple[int, int]] = set()
        """USB filesystems plugged in, mounted or not, by device number."""
        self._tried: set[tuple[int, int]] = set()
        """Drives (by device number) NOCS tried to mount since they were plugged in."""
        self._ejected: set[tuple[int, int]] = set()
        """Ejected and not unplugged yet: they stay unmounted."""
        self._mount_errors: dict[tuple[int, int], str] = {}
        self._config_file = config_dir / "storage.json"
        self._unsaved_dir = data_dir / "unsaved"
        self._internal_dir = internal_dir
        self._longitude = longitude
        self._now = now
        self._paths = paths
        self._search = search
        self._lock = threading.Lock()
        self._config = self._load()
        self._published: dict[str, Json] | None = None
        self._task: asyncio.Task[None] | None = None
        self.catalog: Catalog | None = None
        self._catalog_error: str | None = None
        try:
            self.catalog = Catalog(data_dir / "catalog.sqlite")
        except (CatalogError, OSError, sqlite3.Error) as e:
            log.error("frame catalog unavailable: %s", e)
            self._catalog_error = str(e)

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        await self.refresh()
        self._task = asyncio.get_running_loop().create_task(self._poll(), name="storage-poll")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self.catalog is not None:
            await anyio.to_thread.run_sync(self.catalog.close)

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(POLL_SECONDS)
            try:
                await self.refresh()
            except Exception:
                log.exception("cannot read the mounted volumes")

    async def refresh(self) -> None:
        """Re-read the mounts and free space, mount new drives, and publish what changed."""
        longitude = self._longitude()
        summary = await anyio.to_thread.run_sync(self._summary, longitude)
        if await self._automount():
            summary = await anyio.to_thread.run_sync(self._summary, longitude)
        if summary != self._published:
            self._store.set(ROOT, summary)
            self._published = summary

    # -- commands ---------------------------------------------------------

    async def choose(self, destination: str) -> None:
        """Save to ``auto``, ``internal`` or a mounted volume by id from now on."""
        if destination != AUTO:
            candidates = await anyio.to_thread.run_sync(self._candidates)
            found = next((d for d in candidates if d.id == destination), None)
            if found is None:
                raise StorageError(f"no destination {destination!r} is mounted")
            label = found.label
        else:
            label = None
        self._update(destination=destination, destination_label=label, auto_lock=None)
        await self.refresh()

    async def eject(self, destination_id: str, *, force: bool = False) -> None:
        """Unmount a drive and power it off, once no frame is being saved to it.

        Refused while a job runs, unless ``force``: a sequence saving there would fail.
        """
        if self._helper is None or not self._helper.offers("storage.eject"):
            raise EjectUnavailableError("NOCS cannot eject drives on this computer")
        candidates = await anyio.to_thread.run_sync(self._candidates)
        found = next((d for d in candidates if d.id == destination_id and not d.internal), None)
        if found is None:
            raise StorageError(f"no drive {destination_id!r} is mounted")
        if not force and (kinds := self._busy()):
            raise DriveBusyError(f"{', '.join(kinds)} running: stop it first, or force")
        volume = found.volume
        with self._lock:
            if self._writing[volume.id]:
                raise DriveBusyError(f"a frame is being saved to {found.label}: try again")
            self._ejecting.add(volume.id)
        try:
            log.info("ejecting %s (%s)", found.label, volume.mount.mount_point)
            await self._helper.perform(
                "storage.eject", {"mount_point": str(volume.mount.mount_point)}
            )
            self._ejected.add(volume.mount.device)
        finally:
            with self._lock:
                self._ejecting.discard(volume.id)
        await self.refresh()

    async def _automount(self) -> bool:
        """Mount the USB drives plugged in since the last look; whether it tried any."""
        unmounted = {drive.number for drive in self._unmounted}
        self._tried &= unmounted  # unplugged, or mounted: tried again when it comes back
        self._ejected &= self._present
        self._mount_errors = {n: e for n, e in self._mount_errors.items() if n in unmounted}
        if self._helper is None or not self._helper.offers("storage.mount"):
            return False
        tried = False
        for drive in self._unmounted:
            if drive.number in self._tried or drive.number in self._ejected:
                continue
            self._tried.add(drive.number)
            tried = True
            try:
                await self._helper.perform("storage.mount", {"device": drive.device})
            except Exception as e:  # any refusal or failure is shown on the drive
                log.info("cannot mount %s (%s): %s", drive.label, drive.device, e)
                self._mount_errors[drive.number] = str(e)
            else:
                log.info("mounted %s (%s)", drive.label, drive.device)
        return tried

    async def set_target(self, target: str | None) -> None:
        target = (target or "").strip() or None
        if target is not None and not layout.clean(target):
            raise ValueError("the target name needs letters or digits")
        if target and self.catalog is not None:
            target = await anyio.to_thread.run_sync(self.catalog.target, target)
        self._update(target=target or None)
        await self.refresh()

    async def set_template(self, template: str) -> None:
        self._update(template=layout.check_template(template))
        await self.refresh()

    @property
    def target(self) -> str | None:
        return self._config.target

    # -- saving (blocking: call from a thread) ----------------------------

    def save(self, facts: FrameFacts) -> SavedFrame:
        """Complete the header, move the frame into place and catalog it."""
        writing: list[str] = []
        try:
            return self._save(facts, writing)
        finally:
            with self._lock:
                self._writing.subtract(writing)

    def _save(self, facts: FrameFacts, writing: list[str]) -> SavedFrame:
        if self.catalog is None:
            raise StorageError(f"the frame catalog is unavailable: {self._catalog_error}")
        try:
            header = Header(facts.source)
        except (FitsError, OSError) as e:
            raise StorageError(f"cannot read the frame: {e}") from e
        driver_start = header.start()
        corrected = driver_start is not None and facts.clock_correction != 0
        if driver_start is not None:
            started = driver_start + timedelta(seconds=facts.clock_correction)
        else:
            started = facts.arrived - timedelta(seconds=facts.exposure)
        night = layout.night_of(started, facts.site.longitude if facts.site else None)
        size = facts.source.stat().st_size
        destination = self._checked(self._resolve(Volumes(self._paths), night), size)
        with self._lock:
            if destination.volume.id in self._ejecting:
                raise StorageError(f"{destination.label} is being ejected")
            self._writing[destination.volume.id] += 1
            writing.append(destination.volume.id)

        config = self._config
        filter = header.text("FILTER") or facts.filter
        target = None
        if facts.frame_type == "light":
            target = self.catalog.target(facts.target) if facts.target else config.target
        relative_dir = layout.folder(facts.frame_type, night, target, filter)
        directory = destination.directory / layout.ROOT / relative_dir
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageError(f"cannot create {directory}: {e}") from e
        temperature = header.number("CCD-TEMP")
        if temperature is None:
            temperature = facts.temperature
        stem = layout.file_stem(
            config.template,
            layout.NameFields(
                target=target,
                night=night,
                frame_type=facts.frame_type,
                filter=filter,
                exposure=facts.exposure,
                gain=facts.gain,
                offset=facts.offset,
                temperature=temperature,
                binning=facts.binning,
                camera=facts.camera,
                start=started,
                seq=_count_frames(directory) + 1,
            ),
        )
        suffix = facts.source.suffix or ".fits"
        cards = _cards(facts, target)
        if corrected:
            # The driver stamped the frame with the system clock, which is off.
            start = started.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="milliseconds")
            cards.append(Card("DATE-OBS", start, "UTC start of exposure, corrected by NOCS"))
            cards.append(
                Card("CLOCKCOR", round(facts.clock_correction, 3), "s added to the system clock")
            )
        header.apply(
            cards, overwrite=OWNED_KEYWORDS | ({"DATE-OBS"} if corrected else frozenset[str]())
        )
        for attempt in range(1, 1000):
            name = f"{stem}{f'_{attempt}' if attempt > 1 else ''}{suffix}"
            try:
                place(facts.source, header, directory / name)
            except FileExistsError:
                continue
            break
        else:
            raise StorageError(f"no free file name for {stem} in {directory}")
        relative = relative_dir / name

        width, height = header.number("NAXIS1"), header.number("NAXIS2")
        frame_id = self.catalog.add_frame(
            NewFrame(
                night=night,
                site=(facts.site.name or None) if facts.site else None,
                target=target,
                volume=destination.volume.id,
                volume_label=destination.volume.label,
                mount_point=str(destination.volume.mount.mount_point),
                directory=destination.relative,
                path=relative,
                size=size,
                started=started,
                exposure=facts.exposure,
                frame_type=facts.frame_type,
                filter=filter,
                profile=facts.profile,
                camera=facts.camera,
                gain=facts.gain,
                offset=facts.offset,
                binning=facts.binning,
                temperature=temperature,
                width=int(width) if width is not None else None,
                height=int(height) if height is not None else None,
            )
        )
        if config.destination == AUTO and not destination.internal:
            lock = config.auto_lock
            if lock is None or lock.night != night:
                self._update(
                    auto_lock=AutoLock(
                        night=night, volume=destination.volume.id, label=destination.label
                    )
                )
        return SavedFrame(frame_id, directory / name, relative, destination.id, size, started)

    def keep_unsaved(self, source: Path) -> Path | None:
        """Move a frame that could not be saved out of the way, so it is not lost."""
        try:
            self._unsaved_dir.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(self._unsaved_dir).free
            if free - source.stat().st_size < RESERVE:
                log.error("no room to keep unsaved frame %s; deleting it", source.name)
                source.unlink(missing_ok=True)
                return None
            target = self._unsaved_dir / f"{uuid.uuid4().hex}{source.suffix}"
            shutil.move(source, target)
        except OSError as e:
            log.error("cannot keep unsaved frame %s: %s", source.name, e)
            return None
        return target

    def set_metrics(self, frame_id: int, stars: int | None, hfr: float | None) -> None:
        if self.catalog is not None:
            self.catalog.set_metrics(frame_id, stars, hfr)

    def set_guiding(self, frame_id: int, guiding: Mapping[str, object]) -> None:
        if self.catalog is not None:
            self.catalog.set_guiding(frame_id, guiding)

    def add_temperature(self, sample: TemperatureSample) -> None:
        if self.catalog is not None:
            self.catalog.add_temperature(sample)

    def add_focus_run(self, run: FocusRun) -> int | None:
        return self.catalog.add_focus_run(run) if self.catalog is not None else None

    def start_session(self, session: Session) -> int | None:
        return self.catalog.start_session(session) if self.catalog is not None else None

    def end_session(self, session_id: int, ended: str, outcome: str, error: str | None) -> None:
        if self.catalog is not None:
            self.catalog.end_session(session_id, ended, outcome, error)

    def add_session_events(self, session_id: int, events: list[SessionEvent]) -> None:
        if self.catalog is not None:
            self.catalog.add_session_events(session_id, events)

    # -- catalog queries (blocking) ---------------------------------------

    def temperatures(self, since: str, until: str | None = None) -> list[TemperatureSample]:
        return self._require_catalog().temperatures(since, until)

    def focus_runs(self, limit: int = 20, before: int | None = None) -> list[FocusRun]:
        return self._require_catalog().focus_runs(limit, before)

    def sessions(self, limit: int = 20, before: int | None = None) -> list[Session]:
        return self._require_catalog().sessions(limit, before)

    def session(self, session_id: int) -> tuple[Session, list[SessionEvent]] | None:
        catalog = self._require_catalog()
        session = catalog.session(session_id)
        if session is None:
            return None
        return session, catalog.session_events(session_id)

    def nights(self, night_id: int | None = None) -> list[NightRow]:
        return self._require_catalog().nights(night_id)

    def frames(self, query: FrameFilter) -> list[Located]:
        rows = self._require_catalog().frames(query)
        volumes = Volumes(self._paths)
        return [Located(row, _locate(volumes, row)) for row in rows]

    def frame(self, frame_id: int) -> Located | None:
        row = self._require_catalog().frame(frame_id)
        return Located(row, _locate(Volumes(self._paths), row)) if row is not None else None

    def frame_file(self, frame_id: int) -> tuple[FrameRow, Path]:
        """The file of a frame; raises KeyError, FrameUnavailableError or FileNotFoundError."""
        located = self.frame(frame_id)
        if located is None:
            raise KeyError(frame_id)
        if located.path is None:
            raise FrameUnavailableError(
                f"frame {frame_id} is on {located.row.volume_label}, which is not mounted"
            )
        if not located.path.is_file():
            raise FileNotFoundError(f"frame {frame_id} is no longer at {located.path}")
        return located.row, located.path

    def zip(self, frames: list[Located]) -> tuple[int, Iterator[bytes]]:
        """A zip of frames, with its size, streamed as it is read; paths as below ``NOCS/``."""
        missing = [f.row for f in frames if f.path is None]
        if missing:
            labels = sorted({row.volume_label for row in missing})
            raise FrameUnavailableError(
                f"{len(missing)} frames are on drives that are not mounted: {', '.join(labels)}"
            )
        archive: Any = _zipstream.ZipStream(compress_type=_zipstream.ZIP_STORED, sized=True)
        gone: list[str] = []
        names: set[str] = set()
        for frame in sorted(frames, key=lambda f: (str(f.row.path), f.row.id)):
            assert frame.path is not None
            # A night split between two drives can repeat a name (templates without time).
            path = frame.row.path
            name = str(path)
            for n in range(2, 1000):
                if name not in names:
                    break
                name = str(path.with_stem(f"{path.stem}_{n}"))
            try:
                archive.add_path(str(frame.path), name)
            except FileNotFoundError:
                gone.append(str(frame.row.path))
                continue
            names.add(name)
        if gone:
            archive.add("Not found on disk:\n" + "\n".join(gone) + "\n", "MISSING.txt")
        size: int = len(archive)
        return size, iter(archive)

    def _require_catalog(self) -> Catalog:
        if self.catalog is None:
            raise StorageError(f"the frame catalog is unavailable: {self._catalog_error}")
        return self.catalog

    # -- internals --------------------------------------------------------

    def _candidates(self, volumes: Volumes | None = None) -> list[Destination]:
        volumes = volumes or Volumes(self._paths)
        found: list[Destination] = []
        internal = volumes.destination(self._internal_dir, internal=True)
        if internal is not None:
            found.append(internal)
        found.extend(volumes.external(self._search))
        return found

    def _resolve(self, volumes: Volumes, night: date) -> Destination:
        """The destination for a frame of ``night``; raises StorageError when there is none."""
        config = self._config
        candidates = self._candidates(volumes)
        external = [d for d in candidates if not d.internal]
        if config.destination == AUTO:
            lock = config.auto_lock
            if lock is not None and lock.night == night:
                found = next((d for d in external if d.volume.id == lock.volume), None)
                if found is None:
                    raise StorageError(
                        f"{lock.label}, where tonight's frames are going, is not mounted;"
                        " connect it again or choose another destination"
                    )
                return found
            usable = [d for d in external if d.writable and not d.volume.system]
            if usable:
                return max(usable, key=lambda d: d.free)
            choice = INTERNAL
        else:
            choice = config.destination
        found = next((d for d in candidates if d.id == choice), None)
        if found is None:
            label = config.destination_label or choice
            raise StorageError(f"the destination {label} is not mounted")
        return found

    def _checked(self, destination: Destination, size: int) -> Destination:
        if not destination.writable:
            raise StorageError(f"cannot write to {destination.label} ({destination.directory})")
        # The directory must really be on that filesystem now, not on whatever is
        # under an empty mount point.
        probe = destination.directory
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        major, minor = destination.volume.mount.device
        if os.stat(probe).st_dev != os.makedev(major, minor):
            raise StorageError(f"{destination.label} is no longer mounted")
        if destination.free - size < RESERVE:
            raise StorageError(
                f"{destination.label} is full: {destination.free / 2**30:.1f} GiB free, and"
                f" {RESERVE / 2**30:.0f} GiB must stay free"
            )
        return destination

    def _summary(self, longitude: float | None) -> dict[str, Json]:
        volumes = Volumes(self._paths)
        candidates = self._candidates(volumes)
        self._unmounted = unmounted_usb(self._paths or SystemPaths(), volumes.mounts)
        self._present = {drive.number for drive in self._unmounted} | {
            m.device for m in volumes.mounts if volumes.volume(m).usb
        }
        ejectable = self._helper is not None and self._helper.offers("storage.eject")
        config = self._config
        current: str | None = None
        error: str | None = None
        try:
            night = layout.night_of(self._now(), longitude)
            current = self._checked(self._resolve(volumes, night), 0).id
        except (StorageError, OSError) as e:
            error = str(e)
        if self.catalog is None:
            error = f"the frame catalog is unavailable: {self._catalog_error}"
        return {
            "destinations": [
                d.info() | {"ejectable": ejectable and d.volume.usb and not d.internal}
                for d in candidates
            ],
            "unmounted": [
                {
                    "device": drive.device,
                    "label": drive.label,
                    "fs": drive.fs,
                    "error": self._mount_errors.get(drive.number),
                }
                for drive in self._unmounted
            ],
            "choice": config.destination,
            "destination": current,
            "error": error,
            "target": config.target,
            "template": config.template,
        }

    def _load(self) -> StorageConfig:
        try:
            return StorageConfig.model_validate_json(self._config_file.read_bytes())
        except FileNotFoundError:
            return StorageConfig()
        except (OSError, ValidationError) as e:
            log.warning("ignoring unreadable %s: %s", self._config_file, e)
            return StorageConfig()

    def _update(self, **changes: object) -> None:
        with self._lock:
            config = self._config.model_copy(update=changes)
            write_atomic(self._config_file, config.model_dump_json(indent=2) + "\n")
            self._config = config


def _count_frames(directory: Path) -> int:
    try:
        return sum(
            1 for entry in os.scandir(directory) if entry.name.lower().endswith((".fits", ".fit"))
        )
    except OSError:
        return 0


def _locate(volumes: Volumes, row: FrameRow) -> Path | None:
    return volumes.locate(row.volume, row.directory / layout.ROOT / row.path)


def _cards(facts: FrameFacts, target: str | None) -> list[Card]:
    cards: list[Card] = []
    if target is not None:
        cards.append(Card("OBJECT", target, "Target name"))
    site = facts.site
    if site is not None:
        if site.name:
            cards.append(Card("SITENAME", site.name, "Observing site"))
        cards.append(Card("SITELAT", site.latitude, "Latitude of the imaging site in degrees"))
        cards.append(Card("SITELONG", site.longitude, "Longitude of the imaging site in degrees"))
        cards.append(Card("SITEELEV", site.elevation, "Elevation of the imaging site in metres"))
    optics = facts.optics
    if optics is not None:
        focal_length = optics.focal_length * optics.reducer
        cards.append(Card("FOCALLEN", focal_length, "Focal length in mm"))
        if optics.aperture is not None:
            cards.append(Card("APTDIA", optics.aperture, "Aperture diameter in mm"))
            cards.append(Card("FOCRATIO", round(focal_length / optics.aperture, 2), "Focal ratio"))
    if facts.cooler_target is not None:
        cards.append(Card("SET-TEMP", facts.cooler_target, "Cooler set point in degrees C"))
    for keyword, value, comment in (
        ("AMBTEMP", facts.ambient, "Ambient temperature in degrees C"),
        ("HUMIDITY", facts.humidity, "Relative humidity in percent"),
        ("DEWPOINT", facts.dew_point, "Dew point in degrees C"),
    ):
        if value is not None:
            cards.append(Card(keyword, round(value, 2), comment))
    cards.append(Card("SWCREATE", f"NOCS {__version__}", "Software that wrote the file"))
    return cards
