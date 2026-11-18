"""Masters of a sequence's calibration groups, kept with the night's frames.

When a group of darks, bias or flats ends, its frames are combined in the imaging
worker (``nocs.calibration.master``) and the master is saved through storage as a
frame of its own (``master_dark``, ``master_bias``, ``master_flat``), with a preview.

State under ``("sequence", "master")``: the latest master: its kind, frames, filter,
path below ``NOCS/`` and preview, for the Sequences view's group image.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import anyio

from nocs.calibration.master import GroupMaster, MasterKind
from nocs.imaging.pipeline import FrameAnalysis
from nocs.state import Json, StateStore
from nocs.storage import FrameFacts, FrameRow, FrameUnavailableError, SavedFrame

log = logging.getLogger(__name__)

STATE = ("sequence", "master")


class Worker(Protocol):
    async def group_master(
        self, path: str, kind: MasterKind, frames: list[str]
    ) -> tuple[GroupMaster, FrameAnalysis]: ...


class Library(Protocol):
    """The storage service; every method blocks."""

    def save(self, facts: FrameFacts) -> SavedFrame: ...
    def frame_file(self, frame_id: int) -> tuple[FrameRow, Path]: ...


class GroupMasterService:
    def __init__(
        self,
        store: StateStore,
        worker: Worker,
        library: Callable[[], Library],
        data_dir: Path,
    ) -> None:
        self._store = store
        self._worker = worker
        self._library = library
        self._dir = data_dir / "masters-new"

    def forget(self) -> None:
        """A new run: no master of its own yet."""
        self._store.set(STATE, None)

    async def keep(self, kind: MasterKind, frame_ids: list[int]) -> dict[str, Json] | None:
        """Build and save the master of these frames; what was kept, or None without frames
        at hand (unplugged, deleted)."""
        library = self._library()
        rows: list[FrameRow] = []
        files: list[str] = []
        for frame_id in frame_ids:
            try:
                row, path = await anyio.to_thread.run_sync(library.frame_file, frame_id)
            except (KeyError, OSError, FrameUnavailableError) as e:
                log.debug("group master: frame %d unavailable: %s", frame_id, e)
                continue
            rows.append(row)
            files.append(str(path))
        if not files:
            return None
        await anyio.to_thread.run_sync(lambda: self._dir.mkdir(parents=True, exist_ok=True))
        target = self._dir / f"{uuid.uuid4().hex}.fits"
        try:
            master, preview = await self._worker.group_master(str(target), kind, files)
            first = rows[0]
            facts = FrameFacts(
                source=target,
                frame_type=f"master_{kind}",
                exposure=first.exposure,
                arrived=datetime.now(UTC),
                camera=first.camera,
                gain=first.gain,
                offset=first.offset,
                binning=first.binning,
                temperature=first.temperature,
                cooler_target=None,
                filter=first.filter,
                profile=first.profile,
                site=None,
                optics=None,
            )
            saved = await anyio.to_thread.run_sync(library.save, facts)
        finally:
            await anyio.to_thread.run_sync(lambda: target.unlink(missing_ok=True))
        kept: dict[str, Json] = {
            "kind": kind,
            "frames": master.frames,
            "filter": first.filter,
            "path": str(saved.relative),
            "frame_id": saved.id,
            "preview": {
                "url": f"/api/previews/{Path(preview.preview).name}",
                "width": preview.width,
                "height": preview.height,
            },
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self._store.set(STATE, kept)
        log.info("%s master saved: %s (%d frames)", kind, saved.relative, master.frames)
        return {"master": kind, "frames": master.frames, "path": str(saved.relative)}
