"""The imaging worker process: analysis off the event loop, newest frame wins."""

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_pipeline import star_field, write_fits

from nocs.imaging.worker import ImageWorker, WorkerClosedError


@pytest.fixture
def worker(tmp_path: Path) -> Iterator[ImageWorker]:
    worker = ImageWorker(tmp_path / "previews", keep=2)
    worker.start()
    yield worker
    worker.close()


@pytest.fixture
def frame(tmp_path: Path) -> str:
    return write_fits(tmp_path / "frame.fits", star_field(1200, 800, 20))


async def test_analysis_runs_in_the_worker(worker: ImageWorker, frame: str) -> None:
    result = await worker.analyze("main_camera", frame, None)
    assert result is not None
    assert result.stars >= 15
    name = Path(result.preview).name
    assert worker.preview_path(name) == Path(result.preview)
    assert worker.preview_path("../frame.fits") is None
    assert worker.preview_path("0" * 32 + ".jpg") is None  # well formed, but not there


async def test_newest_frame_replaces_the_waiting_one(worker: ImageWorker, frame: str) -> None:
    first, second, third = await asyncio.gather(
        worker.analyze("main_camera", frame, None),
        worker.analyze("main_camera", frame, None),
        worker.analyze("main_camera", frame, None),
    )
    assert first is not None
    assert second is None
    assert third is not None
    # Another camera is not affected.
    assert await worker.analyze("guide_camera", frame, None) is not None


async def test_measurements_are_never_dropped(worker: ImageWorker, frame: str) -> None:
    results = await asyncio.gather(*(worker.measure(frame, None) for _ in range(3)))
    assert all(r.stars >= 15 for r in results)
    assert not any(worker.previews_dir.glob("*.jpg"))


async def test_old_previews_are_deleted(worker: ImageWorker, frame: str) -> None:
    previews: list[Path] = []
    for _ in range(3):
        result = await worker.analyze("main_camera", frame, None)
        assert result is not None
        previews.append(Path(result.preview))
    assert [p.exists() for p in previews] == [False, True, True]


async def test_old_previews_are_deleted_off_the_event_loop(
    worker: ImageWorker, frame: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On the Pi's microSD an unlink waited up to 4 s for ext4 while a frame was written
    # back, and the event loop with it (soak test, 2026-11-01).
    loop = threading.get_ident()
    unlinked_in: list[int] = []
    unlink = Path.unlink

    def recording(self: Path, missing_ok: bool = False) -> None:
        unlinked_in.append(threading.get_ident())
        unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", recording)
    for _ in range(3):
        assert await worker.analyze("main_camera", frame, None) is not None
    assert unlinked_in
    assert loop not in unlinked_in


async def test_errors_come_back(worker: ImageWorker, tmp_path: Path) -> None:
    (tmp_path / "broken.fits").write_bytes(b"not a FITS file")
    with pytest.raises(OSError, match="not appear to be a valid FITS"):
        await worker.analyze("main_camera", str(tmp_path / "broken.fits"), None)


async def test_only_nocsd_stops_the_worker(tmp_path: Path, frame: str) -> None:
    # Ctrl-C and systemd signal the whole process group; the worker leaves it to nocsd.
    worker = ImageWorker(tmp_path / "previews")
    pool = worker._executor()  # pyright: ignore[reportPrivateUsage]
    pid = await asyncio.get_running_loop().run_in_executor(pool, os.getpid)
    os.kill(pid, signal.SIGINT)
    os.kill(pid, signal.SIGTERM)
    assert await worker.analyze("main_camera", frame, None) is not None
    worker.close()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def running(pid: int) -> bool:
    """Not a zombie: an orphan's exit is reaped by whoever adopted it."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def test_the_worker_ends_with_nocsd(tmp_path: Path) -> None:
    # nocsd killed or crashed never closes the worker: it must not wait for frames forever.
    script = (
        "import asyncio, os, signal, sys\n"
        "from pathlib import Path\n"
        "from nocs.imaging.worker import ImageWorker\n"
        "async def main():\n"
        "    worker = ImageWorker(Path(sys.argv[1]))\n"
        "    pool = worker._executor()\n"
        "    print(await asyncio.get_running_loop().run_in_executor(pool, os.getpid), flush=True)\n"
        "    os.kill(os.getpid(), signal.SIGKILL)\n"
        "asyncio.run(main())\n"
    )
    nocsd = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    assert nocsd.stdout is not None
    pid = int(nocsd.stdout.readline())
    try:
        assert nocsd.wait(30) == -signal.SIGKILL
        deadline = time.monotonic() + 10
        while running(pid):
            assert time.monotonic() < deadline, "the worker outlived nocsd"
            time.sleep(0.1)
    finally:
        if running(pid):
            os.kill(pid, signal.SIGKILL)
        nocsd.stdout.close()


async def test_closing_lets_the_frame_in_hand_finish(tmp_path: Path, frame: str) -> None:
    worker = ImageWorker(tmp_path / "previews")
    task = asyncio.create_task(worker.analyze("main_camera", frame, None))
    await asyncio.sleep(0.5)  # the worker is starting or analysing
    await asyncio.to_thread(worker.close)
    assert await task is not None


async def test_no_worker_starts_once_closed(tmp_path: Path, frame: str) -> None:
    # A frame that arrives while nocsd stops must not spawn a worker mid-shutdown.
    worker = ImageWorker(tmp_path / "previews")
    worker.start()
    worker.close()
    with pytest.raises(WorkerClosedError):
        await worker.analyze("main_camera", frame, None)
    with pytest.raises(WorkerClosedError):
        await worker.measure(frame, None)
