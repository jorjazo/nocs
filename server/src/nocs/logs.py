"""nocsd's log records are written by a thread, never by the event loop.

A handler writes where it was told, and that can wait: on the Pi, an append to a
file on the microSD waited up to 1.9 s while the card wrote back a frame (ext4
``data=ordered``; docs/spikes/pi5-soak.md). Under ``log_to_thread`` every logger,
uvicorn's access log included, hands its records to a queue, and a
``QueueListener`` thread formats and writes them. Leaving it stops the thread
after it has written every record, and later records are written directly.
"""

from __future__ import annotations

import logging
import queue
import sys
from collections.abc import Generator
from contextlib import contextmanager
from logging.handlers import QueueHandler, QueueListener
from typing import TextIO

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@contextmanager
def log_to_thread(level: str, stream: TextIO | None = None) -> Generator[None]:
    """Log at ``level`` to ``stream`` (stderr) from a thread while inside."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(FORMAT))
    records: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    listener = QueueListener(records, handler)
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers = [QueueHandler(records)]
    listener.start()
    try:
        yield
    finally:
        listener.stop()
        root.handlers = [handler]
