"""The imaging worker process: runs the pipeline off the event loop (ADR 0012).

One process, so memory stays bounded on the Pi. Per camera, at most one frame is
analysed and one waits; a newer frame replaces the waiting one, so a busy
pipeline drops frames instead of falling behind (loop mode). Workflows that need
every frame's stars and no preview (autofocus) use ``measure``, which never drops.

Only nocsd stops the worker: it ignores SIGINT and SIGTERM, which a terminal's
Ctrl-C and systemd send to the whole process group, and ``close`` lets it finish
the frame in hand and exit before nocsd does. Killed under the server's feet, it
left tracebacks and multiprocessing's semaphores half cleaned up at every stop.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import re
import signal
import threading
import uuid
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from nocs.imaging import pipeline
from nocs.imaging.pipeline import FrameAnalysis, StarMetrics

log = logging.getLogger(__name__)

KEEP_PREVIEWS = 10
"""Previews kept per camera; older files are deleted."""
PREVIEW_NAME = re.compile(r"^[0-9a-f]{32}\.jpg$")
CLOSE_TIMEOUT = 10.0
"""Seconds ``close`` waits for the frame in hand before killing the worker."""


class WorkerClosedError(RuntimeError):
    """A frame arrived after nocsd closed the worker (shutting down)."""


class ImageWorker:
    def __init__(self, previews_dir: Path, keep: int = KEEP_PREVIEWS) -> None:
        self.previews_dir = previews_dir
        self._keep = keep
        self._pool: ProcessPoolExecutor | None = None
        self._closed = False
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
                self._died()
                raise
            self._remember(key, preview)
            return result

    async def render(
        self, fits_path: str, jpeg_path: str, bayer: str | None, width: int
    ) -> FrameAnalysis:
        """A JPEG of a frame at most ``width`` pixels across, written where asked, and
        its stars (a saved frame's image for the framing chart); none is dropped."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                self._executor(), pipeline.analyze, fits_path, jpeg_path, bayer, width
            )
        except BrokenProcessPool:
            self._died()
            raise

    async def measure(self, fits_path: str, bayer: str | None) -> StarMetrics:
        """Star count and HFR of a frame, without a preview; frames queue, none is dropped."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                self._executor(), pipeline.measure_frame, fits_path, bayer
            )
        except BrokenProcessPool:
            self._died()
            raise

    def preview_path(self, name: str) -> Path | None:
        """The file of a preview by name, if it is one of ours and still exists."""
        if not PREVIEW_NAME.fullmatch(name):
            return None
        path = self.previews_dir / name
        return path if path.is_file() else None

    def close(self, timeout: float = CLOSE_TIMEOUT) -> None:
        """Stop the worker: frames waiting are dropped, the one in hand finishes.

        Blocks until the worker has exited, or kills it after ``timeout``. No
        worker starts again afterwards: frames still arriving fail instead.
        """
        self._closed = True
        pool, self._pool = self._pool, None
        if pool is None:
            return
        # The pool's own shutdown has no timeout: run it aside and wait for it here.
        stopping = threading.Thread(
            target=pool.shutdown, kwargs={"wait": True, "cancel_futures": True}, daemon=True
        )
        stopping.start()
        stopping.join(timeout)
        if stopping.is_alive():
            log.warning("imaging worker still busy after %g s; killing it", timeout)
            # No public way to reach the processes before Python 3.14's kill_workers().
            processes = pool._processes or {}  # pyright: ignore[reportPrivateUsage]
            for process in processes.values():
                process.kill()
            stopping.join(timeout)

    def _died(self) -> None:
        """Forget a broken pool, releasing what it still holds; the next frame starts another."""
        if not self._closed:
            log.error("imaging worker died; starting a new one")
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def _executor(self) -> ProcessPoolExecutor:
        if self._closed:
            raise WorkerClosedError("the imaging worker has been closed")
        if self._pool is None:
            # spawn: a fresh interpreter, not a fork of the server with its sockets and threads.
            self._pool = ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_ignore_stop_signals,
            )
        return self._pool

    def _remember(self, key: str, preview: Path) -> None:
        previews = self._previews[key]
        previews.append(preview)
        while len(previews) > self._keep:
            previews.popleft().unlink(missing_ok=True)


def _ignore_stop_signals() -> None:
    """In the worker: leave stopping to nocsd (see the module's docstring)."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
