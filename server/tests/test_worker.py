"""The imaging worker process: analysis off the event loop, newest frame wins."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_pipeline import star_field, write_fits

from nocs.imaging.worker import ImageWorker


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


async def test_old_previews_are_deleted(worker: ImageWorker, frame: str) -> None:
    previews: list[Path] = []
    for _ in range(3):
        result = await worker.analyze("main_camera", frame, None)
        assert result is not None
        previews.append(Path(result.preview))
    assert [p.exists() for p in previews] == [False, True, True]


async def test_errors_come_back(worker: ImageWorker, tmp_path: Path) -> None:
    (tmp_path / "broken.fits").write_bytes(b"not a FITS file")
    with pytest.raises(OSError, match="not appear to be a valid FITS"):
        await worker.analyze("main_camera", str(tmp_path / "broken.fits"), None)
