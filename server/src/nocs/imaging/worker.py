"""The imaging worker process: runs the pipeline off the event loop (ADR 0012).

One process, so memory stays bounded on the Pi. Per camera, at most one frame is
analysed and one waits; a newer frame replaces the waiting one, so a busy
pipeline drops frames instead of falling behind (loop mode).
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import re
import uuid
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from nocs.imaging import pipeline
from nocs.imaging.pipeline import FrameAnalysis

log = logging.getLogger(__name__)

KEEP_PREVIEWS = 10
"""Previews kept per camera; older files are deleted."""
PREVIEW_NAME = re.compile(r"^[0-9a-f]{32}\.jpg$")


class ImageWorker:
    def __init__(self, previews_dir: Path, keep: int = KEEP_PREVIEWS) -> None:
        self.previews_dir = previews_dir
        self._keep = keep
        self._pool: ProcessPoolExecutor | None = None
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._latest: defaultdict[str, int] = defaultdict(int)
        self._previews: defaultdict[str, deque[Path]] = defaultdict(deque)

    def start(self) -> None:
        """Start the worker now and import the pipeline there, so the first frame is not slow."""
        self._executor().submit(pipeline.warm_up)

    async def analyze(self, key: str, fits_path: str, bayer: str | None) -> FrameAnalysis | None:
        """Preview and metrics for a frame of camera ``key``.

        Returns ``None`` if a newer frame of the same camera arrived while this one
        was waiting.
        """
        self._latest[key] += 1
        ticket = self._latest[key]
        async with self._locks[key]:
            if ticket != self._latest[key]:
                return None
            preview = self.previews_dir / f"{uuid.uuid4().hex}.jpg"
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(
                    self._executor(), pipeline.analyze, fits_path, str(preview), bayer
                )
            except BrokenProcessPool:
                log.error("imaging worker died; starting a new one")
                self._pool = None
                raise
            self._remember(key, preview)
            return result

    def preview_path(self, name: str) -> Path | None:
        """The file of a preview by name, if it is one of ours and still exists."""
        if not PREVIEW_NAME.fullmatch(name):
            return None
        path = self.previews_dir / name
        return path if path.is_file() else None

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def _executor(self) -> ProcessPoolExecutor:
        if self._pool is None:
            # spawn: a fresh interpreter, not a fork of the server with its sockets and threads.
            self._pool = ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn")
            )
        return self._pool

    def _remember(self, key: str, preview: Path) -> None:
        previews = self._previews[key]
        previews.append(preview)
        while len(previews) > self._keep:
            previews.popleft().unlink(missing_ok=True)
