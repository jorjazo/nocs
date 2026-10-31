"""Focusing against the INDI simulators (see simfocus)."""

import asyncio
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from simfocus import APERTURE, FOCAL_LENGTH, FOCUSER, ORION, best_focus

from nocs.devices import Camera, Focuser, FrameType, Mount
from nocs.imaging.worker import ImageWorker
from nocs.indi import BlobMode, IndiClient

pytestmark = pytest.mark.indi

CAMERA = "CCD Simulator"
MOUNT = "Telescope Simulator"


@pytest.fixture
async def client(indi_address: tuple[str, int]) -> AsyncIterator[IndiClient]:
    async with IndiClient(*indi_address) as client:
        yield client


@pytest.fixture
async def camera(client: IndiClient, indi_address: tuple[str, int]) -> AsyncIterator[Camera]:
    """The CCD Simulator at ``FOCAL_LENGTH``, pointed at stars, with its images on a connection
    of their own; its optics are put back afterwards."""
    for name in (MOUNT, CAMERA, FOCUSER):
        await client.wait_for_property(name, "CONNECTION")
    mount, focuser = Mount(client, MOUNT), Focuser(client, FOCUSER)
    await mount.connect()
    await focuser.connect()
    await client.wait_for_property(MOUNT, "EQUATORIAL_EOD_COORD")
    await client.wait_for_property(FOCUSER, "FWHM")
    if mount.parked:
        await mount.unpark()
    await mount.goto(*ORION)

    images = IndiClient(*indi_address)
    await images.connect(device=CAMERA)
    camera = Camera(client, CAMERA, images)
    await camera.connect()
    await images.wait_for_property(CAMERA, "CCD1")
    await images.enable_blob(CAMERA, BlobMode.ONLY, "CCD1")
    await client.wait_for_property(CAMERA, "CCD_INFO")
    await camera.set_binning(1)
    await camera.set_region(None)
    await camera.set_frame_type(FrameType.LIGHT)
    await camera.set_optics(FOCAL_LENGTH, APERTURE)
    start = focuser.position
    try:
        yield camera
    finally:
        await camera.set_optics(250, 50)  # the dev profile's
        await focuser.move_to(start)
        await images.close()


@pytest.fixture
def worker(tmp_path: Path) -> Iterator[ImageWorker]:
    worker = ImageWorker(tmp_path / "previews")
    worker.start()
    yield worker
    worker.close()


async def test_the_simulated_stars_follow_the_focuser(
    client: IndiClient, camera: Camera, worker: ImageWorker, tmp_path: Path
) -> None:
    best = round(await best_focus(client))
    assert 30000 < best < 45000
    focuser = Focuser(client, FOCUSER)

    async def hfr_at(position: int) -> float:
        await focuser.move_to(position)
        await asyncio.sleep(0.2)  # the camera reads the new FWHM through indiserver
        frame = await camera.expose(2)
        with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".fits") as f:
            f.write(frame.data)
            f.flush()
            metrics = await worker.measure(f.name, None)
        assert metrics.stars >= 20
        assert metrics.hfr is not None
        return metrics.hfr

    inside, focused, outside = [await hfr_at(best + d) for d in (-10000, 0, 10000)]
    assert focused < inside / 1.3
    assert focused < outside / 1.3
    assert inside == pytest.approx(outside, rel=0.25)
