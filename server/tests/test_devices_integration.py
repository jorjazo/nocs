"""Typed devices against the INDI simulators (see conftest.indi_address)."""

from collections.abc import AsyncIterator

import pytest

from nocs.devices import Camera, FilterWheel, Focuser, FrameType, Mount
from nocs.indi import IndiClient

pytestmark = pytest.mark.indi


@pytest.fixture
async def client(indi_address: tuple[str, int]) -> AsyncIterator[IndiClient]:
    async with IndiClient(*indi_address) as client:
        await client.wait_for(
            lambda c: all(
                c.get_property(d, "DRIVER_INFO") is not None
                for d in (
                    "Telescope Simulator",
                    "CCD Simulator",
                    "Focuser Simulator",
                    "Filter Simulator",
                )
            )
        )
        yield client


async def test_discovery_by_interface(client: IndiClient) -> None:
    assert "Telescope Simulator" in [m.name for m in Mount.find_all(client)]
    assert "CCD Simulator" in [c.name for c in Camera.find_all(client)]
    assert "Focuser Simulator" in [f.name for f in Focuser.find_all(client)]
    wheels = [w.name for w in FilterWheel.find_all(client)]
    assert {"Filter Simulator", "CCD Simulator"} <= set(wheels)


async def test_focuser_move(client: IndiClient) -> None:
    focuser = Focuser(client, "Focuser Simulator")
    await focuser.connect()
    await client.wait_for_property(focuser.name, "ABS_FOCUS_POSITION")
    target = 30500 if focuser.position != 30500 else 30000
    await focuser.move_to(target)
    assert focuser.position == target
    assert not focuser.moving


async def test_filter_wheel_select(client: IndiClient) -> None:
    wheel = FilterWheel(client, "Filter Simulator")
    await wheel.connect()
    await client.wait_for_property(wheel.name, "FILTER_NAME")
    target = "Green" if wheel.filter != "Green" else "Blue"
    await wheel.select(target)
    assert wheel.filter == target
    await wheel.select(1)
    assert wheel.slot == 1


async def test_camera_dark_exposure(client: IndiClient) -> None:
    camera = Camera(client, "CCD Simulator")
    await camera.connect()
    await client.wait_for_property(camera.name, "CCD_INFO")
    assert camera.sensor.width > 0

    frame = await camera.expose(0.2, frame_type=FrameType.DARK)

    assert camera.frame_type is FrameType.DARK
    assert frame.format.startswith(".fits")
    assert frame.data.startswith(b"SIMPLE")
    assert b"IMAGETYP= 'Dark" in frame.data[: 2880 * 4]
    await camera.set_frame_type(FrameType.LIGHT)


async def test_mount_goto_and_tracking(client: IndiClient) -> None:
    mount = Mount(client, "Telescope Simulator")
    await mount.connect()
    await client.wait_for_property(mount.name, "EQUATORIAL_EOD_COORD")
    await mount.unpark()

    start = mount.coordinates
    ra = (start.ra + 0.5) % 24
    dec = 60.0 if abs(start.dec - 60.0) > 1 else 50.0
    await mount.goto(ra, dec)

    assert mount.coordinates.ra == pytest.approx(ra, abs=0.01)
    assert mount.coordinates.dec == pytest.approx(dec, abs=0.1)
    assert mount.tracking
    await mount.set_tracking(False)
    assert not mount.tracking


async def test_mount_rejects_bad_coordinates(client: IndiClient) -> None:
    mount = Mount(client, "Telescope Simulator")
    with pytest.raises(ValueError, match="out of range"):
        await mount.goto(25, 0)
