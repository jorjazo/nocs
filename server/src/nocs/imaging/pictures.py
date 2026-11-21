"""Full-size JPEGs of what the viewer shows, for visitors to keep (the Visitors view):
the main camera's latest frame, and the live stack as it stands.

Rendered on demand in the imaging worker (a 26 MP frame takes a few seconds of the
Pi's CPU) and kept in ``<data>/pictures/`` until the frame, or the stack's frames or
look, change: many visitors downloading the same picture cost one render. Only the
latest picture of each kind is kept. JPEGs carry no location (no EXIF is written).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import anyio

from nocs.equipment import Role
from nocs.imaging.capture import KeptFrame, hold_frame
from nocs.stacking.service import NothingToSaveError

log = logging.getLogger(__name__)

type Kind = Literal["frame", "stack"]


class NothingToShowError(Exception):
    """No frame, or no stack, to make a picture of."""


class _Replaced(Exception):
    """The frame was replaced (and deleted) before it could be held."""


@dataclass(frozen=True, slots=True)
class Picture:
    path: Path
    name: str
    """A file name for the download: NOCS_<what>_<UTC time>.jpg."""


class Renderer(Protocol):
    async def picture(
        self, fits_path: str, jpeg_path: str, bayer: str | None
    ) -> tuple[int, int]: ...


class Stacker(Protocol):
    def picture_key(self) -> str | None: ...
    def picture_name(self) -> str | None: ...
    async def picture(self, path: Path) -> None:
        """Raises ``nocs.stacking.service.NothingToSaveError`` without a stack to show."""
        ...


@dataclass(slots=True)
class _Kept:
    key: str
    picture: Picture


class Pictures:
    def __init__(
        self,
        directory: Path,
        worker: Renderer,
        kept: Callable[[Role], KeptFrame | None],
        stacker: Callable[[], Stacker | None],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._directory = directory
        self._worker = worker
        self._kept = kept
        self._stacker = stacker
        self._now = now
        self._pictures: dict[Kind, _Kept] = {}
        self._locks: dict[Kind, anyio.Lock] = {"frame": anyio.Lock(), "stack": anyio.Lock()}

    async def frame(self) -> Picture:
        """The main camera's frame behind its preview, at its full size; a frame replaced
        while it was asked for gives the one that replaced it."""
        try:
            return await self._frame()
        except _Replaced:
            try:
                return await self._frame()
            except _Replaced:
                raise NothingToShowError("frames come too fast: try again") from None

    async def _frame(self) -> Picture:
        # Off the loop: whether the frame is still on disk can wait on the microSD.
        kept = await anyio.to_thread.run_sync(self._kept, Role.MAIN_CAMERA)
        if kept is None:
            raise NothingToShowError("no frame yet")
        shot, owned = kept.shot, kept.owned
        key = f"{shot.path.name}-{shot.taken.isoformat()}"
        name = _name("frame", shot.taken)

        async def render(path: Path) -> None:
            if not owned:  # a saved frame: nothing deletes it
                await self._worker.picture(str(shot.path), str(path), shot.bayer)
                return
            # A newer frame may replace (and delete) this one meanwhile: render a link,
            # beside it (a hard link cannot cross to another drive).
            link = shot.path.with_name(
                f"{shot.path.stem}.picture-{uuid.uuid4().hex}{shot.path.suffix}"
            )
            try:
                await anyio.to_thread.run_sync(hold_frame, shot.path, link)
            except FileNotFoundError:
                raise _Replaced from None
            try:
                await self._worker.picture(str(link), str(path), shot.bayer)
            finally:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(lambda: link.unlink(missing_ok=True))

        return await self._get("frame", key, name, render)

    async def stack(self) -> Picture:
        """The live stack as it stands, with its look, at its full size."""
        stacker = self._stacker()
        key = stacker.picture_key() if stacker is not None else None
        if stacker is None or key is None:
            raise NothingToShowError("no stack yet")
        name = _name(stacker.picture_name() or "stack", self._now())

        async def render(path: Path) -> None:
            try:
                await stacker.picture(path)
            except NothingToSaveError as e:  # ended, lost or not covered yet
                raise NothingToShowError(str(e)) from None

        return await self._get("stack", key, name, render)

    async def _get(
        self, kind: Kind, key: str, name: str, render: Callable[[Path], Awaitable[None]]
    ) -> Picture:
        async with self._locks[kind]:
            kept = self._pictures.get(kind)
            if (
                kept is not None
                and kept.key == key
                and await anyio.Path(kept.picture.path).is_file()
            ):
                return kept.picture
            await anyio.to_thread.run_sync(
                lambda: self._directory.mkdir(parents=True, exist_ok=True)
            )
            path = self._directory / f"{kind}-{uuid.uuid4().hex}.jpg"
            await render(path)
            picture = Picture(path, name)
            self._pictures[kind] = _Kept(key, picture)
            if kept is not None and kept.picture.path != path:
                # A download of it under way keeps reading it: an unlinked file stays open.
                old = kept.picture.path
                await anyio.to_thread.run_sync(lambda: old.unlink(missing_ok=True))
            return picture

    def clear(self) -> None:
        """Delete what an earlier run left (nocsd starting); never raises."""
        try:
            if self._directory.is_dir():
                for path in self._directory.iterdir():
                    if path.is_file():
                        path.unlink(missing_ok=True)
        except OSError as e:
            log.warning("cannot clear %s: %s", self._directory, e)


def _name(what: str, when: datetime) -> str:
    stamp = when.astimezone(UTC).strftime("%Y%m%d_%H%M%S")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", what).strip("_") or "frame"
    return f"NOCS_{cleaned}_{stamp}.jpg"
