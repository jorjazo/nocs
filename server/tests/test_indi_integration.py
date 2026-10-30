"""Integration tests against the INDI simulators (see conftest.indi_address)."""

import pytest

from nocs.indi import BlobElement, BlobMode, IndiClient, PropertyState

pytestmark = pytest.mark.indi

FOCUSER = "Focuser Simulator"
CCD = "CCD Simulator"


async def connect_device(client: IndiClient, device: str) -> None:
    await client.wait_for_property(device, "CONNECTION")
    await client.send_switch(device, "CONNECTION", {"CONNECT": True, "DISCONNECT": False})
    await client.wait_for(
        lambda c: (
            (p := c.get_property(device, "CONNECTION")) is not None
            and p.switch("CONNECT")
            and p.state is PropertyState.OK
        )
    )


async def test_lists_simulator_devices(indi_address: tuple[str, int]) -> None:
    async with IndiClient(*indi_address) as client:
        await client.wait_for(lambda c: {FOCUSER, CCD} <= set(c.devices))
        assert client.get_property(CCD, "CONNECTION") is not None


async def test_move_focuser(indi_address: tuple[str, int]) -> None:
    async with IndiClient(*indi_address) as client:
        await connect_device(client, FOCUSER)
        position = await client.wait_for_property(FOCUSER, "ABS_FOCUS_POSITION")
        target = 31000.0 if position.number("FOCUS_ABSOLUTE_POSITION") != 31000 else 29000.0

        await client.send(FOCUSER, "ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": target})
        await client.wait_for(
            lambda _: (
                position.state is PropertyState.OK
                and position.number("FOCUS_ABSOLUTE_POSITION") == target
            ),
            timeout=30,
        )


async def test_expose_and_receive_fits(indi_address: tuple[str, int]) -> None:
    async with IndiClient(*indi_address) as client:
        await connect_device(client, CCD)
        await client.wait_for_property(CCD, "CCD_EXPOSURE")
        await client.enable_blob(CCD, BlobMode.ALSO)
        image = await client.wait_for_property(CCD, "CCD1")
        blob = image.elements["CCD1"]
        assert isinstance(blob, BlobElement)
        blob.data = None

        await client.send(CCD, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": 0.5})
        await client.wait_for(lambda _: blob.data is not None, timeout=30)

        assert blob.data is not None
        assert blob.format.startswith(".fits")
        assert blob.data.startswith(b"SIMPLE")


async def test_send_rejects_unknown_property(indi_address: tuple[str, int]) -> None:
    async with IndiClient(*indi_address) as client:
        await client.wait_for_property(CCD, "CONNECTION")
        with pytest.raises(KeyError):
            await client.send(CCD, "NOPE", {"X": 1})
        with pytest.raises(KeyError):
            await client.send(CCD, "CONNECTION", {"NOPE": True})
