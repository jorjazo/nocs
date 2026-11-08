"""A live stack of synthetic frames saved through the real storage (ADR 0039, S6)."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from synthstars import render, sky
from test_storage_service import (  # noqa: F401 (fixtures)
    SITE,
    Rig,
    rig,  # pyright: ignore[reportUnusedImport]
    shm,  # pyright: ignore[reportUnusedImport]
)

from nocs.stacking import masters, stack
from nocs.stacking.frames import Offered
from nocs.stacking.masters import Calibration, Kind, Master
from nocs.stacking.register import Transform
from nocs.stacking.service import LiveStackService
from nocs.stacking.stack import Added, Look, Rendered
from nocs.storage import FrameFilter
from nocs.storage.service import StorageService

_fits: Any = fits

WIDTH, HEIGHT = 800, 600


@dataclass
class DirectWorker:
    """The imaging worker's stacking calls, run in this process (in a thread)."""

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
    ) -> Added:
        preview = str(self.previews_dir / f"{stack_id}-{datetime.now(UTC).timestamp()}.jpg")
        call = functools.partial(
            stack.add_frame,
            stack_id,
            fits_path,
            bayer,
            new=new,
            stars=stars,
            hfr=hfr,
            preview_path=preview,
            look=look,
            calibration=calibration,
        )
        return await asyncio.to_thread(call)

    async def stack_render(self, stack_id: str, look: Look) -> Rendered:
        return await asyncio.to_thread(
            stack.render, stack_id, str(self.previews_dir / "r.jpg"), look
        )

    async def stack_drop(self, stack_id: str) -> None:
        stack.drop(stack_id)

    async def stack_save(
        self,
        stack_id: str,
        fits_path: str,
        jpeg_path: str,
        look: Look,
        header: dict[str, str | int | float | bool | None],
    ) -> Rendered:
        return await asyncio.to_thread(stack.save, stack_id, fits_path, jpeg_path, look, header)

    async def build_master(
        self,
        path: str,
        kind: Kind,
        frames: list[str],
        bayer: str | None,
        subtract: str | None = None,
    ) -> Master:
        return await asyncio.to_thread(masters.build, path, kind, frames, bayer, subtract=subtract)


@pytest.fixture
async def storage(rig: Rig) -> AsyncIterator[StorageService]:  # noqa: F811
    service = rig.service()
    await service.refresh()
    yield service
    await service.close()


async def test_a_stack_is_saved_as_a_frame_of_the_night(
    rig: Rig,  # noqa: F811
    storage: StorageService,
    tmp_path: Path,
) -> None:
    stack.drop_all()
    previews = tmp_path / "previews"
    previews.mkdir()
    service = LiveStackService(
        rig.store, DirectWorker(previews), lambda: storage, rig.config, rig.data
    )
    await service.set_on(True)
    task = asyncio.create_task(service.run())
    field = sky(400, WIDTH, HEIGHT, seed=8)
    start = datetime(2026, 10, 31, 1, 0, tzinfo=UTC)
    try:
        for i in range(3):
            raw = render(
                field,
                WIDTH,
                HEIGHT,
                Transform.of(0.0, (2.0 * i, 0.0)),
                sigma=2.6,
                bayer="RGGB",
                seed=i,
            )
            path = tmp_path / f"light{i}.fits"
            hdu = _fits.PrimaryHDU(raw)
            hdu.header["BAYERPAT"] = "RGGB"
            hdu.writeto(path)
            await service.offer(
                Offered(
                    path=path,
                    owned=False,
                    bayer="RGGB",
                    taken=start + timedelta(seconds=30 * (i + 1)),
                    night=date(2026, 10, 30),
                    exposure=30.0,
                    camera="CCD Simulator",
                    gain=100.0,
                    offset=10.0,
                    binning=1,
                    temperature=-10.0,
                    filter=None,
                    target="NGC 253",
                    site=SITE,
                )
            )
            await service.idle()
        saved = await service.save()
    finally:
        task.cancel()
        stack.drop_all()

    # In the night of its frames, under Stack/<target>/, with its JPEG beside it.
    assert str(saved.relative).startswith("2026-10-30/Stack/NGC_253/")
    assert saved.path.is_file()
    assert saved.path.with_suffix(".jpg").is_file()
    rows = await asyncio.to_thread(storage.frames, FrameFilter(frame_type="stack"))
    assert len(rows) == 1
    row = rows[0].row
    assert (row.frame_type, row.exposure, row.target) == ("stack", 90.0, "NGC 253")
    assert (row.width, row.height) == (WIDTH // 2, HEIGHT // 2)
    with _fits.open(saved.path) as hdul:
        data = np.asarray(hdul[0].data)
        header = hdul[0].header
        assert data.shape == (3, HEIGHT // 2, WIDTH // 2)
        assert header["NCOMBINE"] == 3
        assert header["EXPTIME"] == 30.0
        assert header["LIVETIME"] == 90.0
        assert header["OBJECT"] == "NGC 253"
        assert header["IMAGETYP"] == "Live stack"
        assert header["DATE-OBS"] == "2026-10-31T01:00:00"
        assert header["SITELAT"] == SITE.latitude
    # Never listed as a light (the calibration library and the session report read lights).
    lights = await asyncio.to_thread(storage.frames, FrameFilter(frame_type="light"))
    assert lights == []
