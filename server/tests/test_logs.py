"""nocsd's log records are written by a thread, and all of them come out."""

import io
import logging
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from nocs.logs import log_to_thread


class SlowStream(io.StringIO):
    """A sink that waits, as a file on the microSD does while a frame is written back."""

    def __init__(self) -> None:
        super().__init__()
        self.threads: set[str] = set()

    def write(self, s: str) -> int:
        self.threads.add(threading.current_thread().name)
        time.sleep(0.2)
        return super().write(s)


@pytest.fixture(autouse=True)
def restore_root() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers, root.level = handlers, level


def test_records_are_written_by_a_thread_and_all_come_out() -> None:
    stream = SlowStream()
    log = logging.getLogger("nocs.test")
    with log_to_thread("info", stream):
        start = time.monotonic()
        for i in range(5):
            log.info("record %d", i)
        log.debug("below the level")
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("failed")
        assert time.monotonic() - start < 0.1
    lines = stream.getvalue()
    for i in range(5):
        assert f"INFO nocs.test: record {i}" in lines
    assert "below the level" not in lines
    assert "ERROR nocs.test: failed" in lines
    assert "ValueError: boom" in lines
    assert threading.current_thread().name not in stream.threads

    log.warning("after")  # written directly once the thread has stopped
    assert "WARNING nocs.test: after" in stream.getvalue()


def test_uvicorns_access_log_goes_through_the_queue() -> None:
    stream = io.StringIO()
    with log_to_thread("info", stream):
        uvicorn.Config(app=lambda: None, log_config=None, log_level="info").configure_logging()
        access = logging.getLogger("uvicorn.access")
        assert not access.handlers
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/api/health", "1.1", 200)
    assert 'INFO uvicorn.access: 127.0.0.1:5000 - "GET /api/health HTTP/1.1" 200' in (
        stream.getvalue()
    )
