"""Camera facade: vendor-specific controls, regions, images on a separate connection."""

import asyncio
from collections.abc import Mapping

import pytest
from fakes import FakeClient, number_property, switch_property

from nocs.devices import Camera, DeviceError
from nocs.devices.camera import Region
from nocs.indi import Permission, Property, PropertyState, PropertyType
from nocs.indi.properties import BlobElement, NumberElement, TextElement


def camera_client(name: str = "Cam") -> FakeClient:
    client = FakeClient()
    client.define(
        number_property(
            name,
            "CCD_INFO",
            CCD_MAX_X=6248,
            CCD_MAX_Y=4176,
            CCD_PIXEL_SIZE_X=3.76,
            CCD_PIXEL_SIZE_Y=3.76,
            CCD_BITSPERPIXEL=16,
        )
    )
    client.define(number_property(name, "CCD_EXPOSURE", CCD_EXPOSURE_VALUE=0))
    client.define(number_property(name, "CCD_FRAME", X=0, Y=0, WIDTH=6248, HEIGHT=4176))
    client.define(
        switch_property(
            name,
            "CCD_FRAME_TYPE",
            FRAME_LIGHT=True,
            FRAME_BIAS=False,
            FRAME_DARK=False,
            FRAME_FLAT=False,
        )
    )
    blob = Property(name, "CCD1", PropertyType.BLOB)
    blob.elements["CCD1"] = BlobElement("CCD1", "Image")
    client.define(blob)
    return client


def asi_controls(name: str = "Cam") -> Property:
    prop = Property(name, "CCD_CONTROLS", PropertyType.NUMBER, state=PropertyState.IDLE)
    prop.elements["Gain"] = NumberElement("Gain", "Gain", 200, min=-25, max=700)
    prop.elements["Offset"] = NumberElement("Offset", "Offset", 1, min=0, max=240)
    prop.elements["WB_R"] = NumberElement("WB_R", "WB_R", 52, min=1, max=99)
    return prop


def acknowledge(client: FakeClient) -> None:
    """Drivers answer every command with Ok and the new values."""

    def respond(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        text = {k: str(v) for k, v in values.items()}
        asyncio.get_running_loop().call_soon(client.update, device, name, PropertyState.OK, text)

    client.responder = respond


async def test_zwo_gain_and_offset_live_in_ccd_controls() -> None:
    client = camera_client()
    client.define(asi_controls())
    acknowledge(client)
    camera = Camera(client, "Cam")
    assert (camera.gain, camera.offset) == (200, 1)
    range_ = camera.gain_range
    assert range_ is not None
    assert (range_.min, range_.max) == (-25, 700)
    await camera.set_gain(300)
    await camera.set_offset(50)
    assert client.sent == [
        ("Cam", "CCD_CONTROLS", {"Gain": 300}),
        ("Cam", "CCD_CONTROLS", {"Offset": 50}),
    ]
    assert (camera.gain, camera.offset) == (300, 50)
    with pytest.raises(ValueError, match=r"outside -25\.\.700"):
        await camera.set_gain(701)


async def test_simulator_gain_and_offset_have_their_own_properties() -> None:
    client = camera_client()
    client.define(number_property("Cam", "CCD_GAIN", GAIN=90))
    client.define(number_property("Cam", "CCD_OFFSET", OFFSET=0))
    acknowledge(client)
    camera = Camera(client, "Cam")
    await camera.set_gain(120)
    assert client.sent == [("Cam", "CCD_GAIN", {"GAIN": 120})]
    assert camera.gain == 120


async def test_camera_without_gain() -> None:
    camera = Camera(camera_client(), "Cam")
    assert camera.gain is None
    assert camera.gain_range is None
    with pytest.raises(DeviceError, match="no gain control"):
        await camera.set_gain(100)


async def test_region() -> None:
    client = camera_client()
    acknowledge(client)
    camera = Camera(client, "Cam")
    assert camera.region == Region(0, 0, 6248, 4176)
    await camera.set_region(Region(100, 200, 640, 480))
    assert camera.region == Region(100, 200, 640, 480)
    await camera.set_region(None)
    assert camera.region == Region(0, 0, 6248, 4176)
    with pytest.raises(ValueError, match="outside the 6248x4176 sensor"):
        await camera.set_region(Region(6000, 0, 640, 480))


def test_bayer_pattern() -> None:
    client = camera_client()
    camera = Camera(client, "Cam")
    assert camera.bayer_pattern is None
    cfa = Property("Cam", "CCD_CFA", PropertyType.TEXT)
    cfa.elements["CFA_TYPE"] = TextElement("CFA_TYPE", "Type", "RGGB")
    client.define(cfa)
    assert camera.bayer_pattern == "RGGB"


def test_only_a_settable_temperature_means_a_cooler() -> None:
    client = camera_client()
    camera = Camera(client, "Cam")
    assert not camera.can_cool
    # An uncooled ZWO camera (the ASI220MM guide sensor) reports its temperature read-only.
    temperature = number_property("Cam", "CCD_TEMPERATURE", CCD_TEMPERATURE_VALUE=24.5)
    client.define(temperature)
    assert camera.temperature == 24.5
    assert not camera.can_cool
    temperature.perm = Permission.READ_WRITE
    assert camera.can_cool


async def test_images_arrive_on_their_own_connection() -> None:
    control, images = camera_client(), camera_client()
    camera = Camera(control, "Cam", images)

    def respond(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        if name == "CCD_EXPOSURE":
            asyncio.get_running_loop().call_later(
                0.01, images.deliver_blob, "Cam", "CCD1", b"SIMPLE  =   T"
            )

    control.responder = respond
    frame = await camera.expose(0.5)
    assert (frame.data, frame.format, frame.exposure) == (b"SIMPLE  =   T", ".fits", 0.5)
    # Nothing enabled BLOBs on the control connection, and the image is not kept around.
    assert [name for _, name, _ in control.sent] == ["CCD_EXPOSURE"]
    blob = images.get_property("Cam", "CCD1")
    assert blob is not None
    element = blob.elements["CCD1"]
    assert isinstance(element, BlobElement)
    assert element.data is None


async def test_cancelled_exposure_is_aborted() -> None:
    client = camera_client()

    def respond(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        if name == "CCD_EXPOSURE":
            client.update("Cam", "CCD_EXPOSURE", PropertyState.BUSY, {"CCD_EXPOSURE_VALUE": "60"})

    client.responder = respond
    client.define(switch_property("Cam", "CCD_ABORT_EXPOSURE", ABORT=False))
    camera = Camera(client, "Cam", images=camera_client())
    task = asyncio.create_task(camera.expose(60))
    await asyncio.sleep(0.01)
    assert camera.exposing
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.sent[-1] == ("Cam", "CCD_ABORT_EXPOSURE", {"ABORT": True})


async def test_driver_saves_the_image_itself() -> None:
    client = camera_client()
    settings = Property("Cam", "UPLOAD_SETTINGS", PropertyType.TEXT, state=PropertyState.IDLE)
    for name, value in (("UPLOAD_DIR", "/home"), ("UPLOAD_PREFIX", "IMAGE_XXX")):
        settings.elements[name] = TextElement(name, name, value)
    client.define(settings)
    modes = {"UPLOAD_CLIENT": True, "UPLOAD_LOCAL": False, "UPLOAD_BOTH": False}
    client.define(switch_property("Cam", "UPLOAD_MODE", **modes))

    def respond(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        loop = asyncio.get_running_loop()
        if name == "CCD_EXPOSURE":
            saved = Property("Cam", "CCD_FILE_PATH", PropertyType.TEXT, state=PropertyState.OK)
            saved.elements["FILE_PATH"] = TextElement("FILE_PATH", "", "/run/up/NOCS_001.fits")
            loop.call_later(0.01, client.define, saved)
        else:
            update = {
                k: ("On" if v else "Off") if isinstance(v, bool) else str(v)
                for k, v in values.items()
            }
            loop.call_soon(client.update, device, name, PropertyState.OK, update)

    client.responder = respond
    camera = Camera(client, "Cam")
    path = await camera.expose_to_file(1, directory="/run/up", prefix="NOCS_XXX")
    assert path == "/run/up/NOCS_001.fits"
    assert [name for _, name, _ in client.sent] == [
        "UPLOAD_SETTINGS",
        "UPLOAD_MODE",
        "CCD_EXPOSURE",
    ]
    mode = client.get_property("Cam", "UPLOAD_MODE")
    assert mode is not None
    assert mode.switch("UPLOAD_LOCAL")


async def test_a_path_resent_mid_exposure_is_not_the_new_frame() -> None:
    client = camera_client()
    settings = Property("Cam", "UPLOAD_SETTINGS", PropertyType.TEXT, state=PropertyState.OK)
    for name, value in (("UPLOAD_DIR", "/run/up"), ("UPLOAD_PREFIX", "NOCS_XXX")):
        settings.elements[name] = TextElement(name, name, value)
    client.define(settings)
    modes = {"UPLOAD_CLIENT": False, "UPLOAD_LOCAL": True, "UPLOAD_BOTH": False}
    client.define(switch_property("Cam", "UPLOAD_MODE", **modes))

    def path(value: str) -> Property:
        prop = Property("Cam", "CCD_FILE_PATH", PropertyType.TEXT, state=PropertyState.OK)
        prop.elements["FILE_PATH"] = TextElement("FILE_PATH", "", value)
        return prop

    client.define(path("/run/up/NOCS_001.fits"))  # the previous frame

    def respond(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        loop = asyncio.get_running_loop()
        # Another client connects: indiserver re-sends the definition, mid-exposure.
        loop.call_later(0.01, client.define, path("/run/up/NOCS_001.fits"))
        # The driver saves the new frame (reusing the name) and updates the property.
        new = {"FILE_PATH": "/run/up/NOCS_001.fits"}
        loop.call_later(0.03, client.update, "Cam", "CCD_FILE_PATH", PropertyState.OK, new)

    client.responder = respond
    camera = Camera(client, "Cam")
    events: list[str] = []
    client.add_listener(lambda e: events.append(type(e).__name__))
    written = await camera.expose_to_file(1, directory="/run/up", prefix="NOCS_XXX")
    assert written == "/run/up/NOCS_001.fits"
    assert events[-1] == "PropertyUpdated"  # it waited for the update, not the re-send
