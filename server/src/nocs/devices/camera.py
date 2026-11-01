from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from nocs.devices.base import Device, DeviceError, DeviceInterface, event_device
from nocs.indi import (
    BlobElement,
    BlobMode,
    ConnectionLost,
    IndiClient,
    IndiEvent,
    NumberElement,
    Permission,
    Property,
    PropertyDefined,
    PropertyState,
    PropertyUpdated,
    TextElement,
)

DOWNLOAD_MARGIN = 60.0
"""Extra time allowed beyond the exposure for readout and transfer."""


class FrameType(StrEnum):
    LIGHT = "FRAME_LIGHT"
    BIAS = "FRAME_BIAS"
    DARK = "FRAME_DARK"
    FLAT = "FRAME_FLAT"


@dataclass(frozen=True, slots=True)
class SensorInfo:
    width: int
    height: int
    pixel_size_x: float
    pixel_size_y: float
    bits_per_pixel: int


@dataclass(frozen=True, slots=True)
class Frame:
    data: bytes
    format: str
    exposure: float


@dataclass(frozen=True, slots=True)
class Region:
    """Part of the sensor to read out, in unbinned pixels."""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Range:
    min: float
    max: float


# Gain and offset live in vendor-specific places: (property, element) in order of preference.
_GAIN = (("CCD_CONTROLS", "Gain"), ("CCD_GAIN", "GAIN"))
_OFFSET = (("CCD_CONTROLS", "Offset"), ("CCD_OFFSET", "OFFSET"))


class Camera(Device):
    """Main imaging sensor of a camera (``CCD_*`` properties, image in ``CCD1``).

    Images arrive on ``images``, a separate connection that receives only this
    camera's BLOBs, so frames tens of megabytes large do not hold up the
    connection that carries every other device's state. Without one, BLOBs are
    enabled on the main connection.
    """

    INTERFACE = DeviceInterface.CCD
    REQUIRED = ("CCD_INFO", "CCD_EXPOSURE", "CCD_FRAME_TYPE", "CCD1")

    def __init__(self, client: IndiClient, name: str, images: IndiClient | None = None) -> None:
        super().__init__(client, name)
        self.images = images

    def not_ready(self) -> list[str]:
        # Drivers define CCD_INFO first and fill in the sensor size a moment later.
        missing = super().not_ready()
        if not missing and self.prop("CCD_INFO").number("CCD_MAX_X") <= 0:
            missing.append("sensor size (CCD_INFO)")
        return missing

    @property
    def sensor(self) -> SensorInfo:
        info = self.prop("CCD_INFO")
        return SensorInfo(
            width=round(info.number("CCD_MAX_X")),
            height=round(info.number("CCD_MAX_Y")),
            pixel_size_x=info.number("CCD_PIXEL_SIZE_X"),
            pixel_size_y=info.number("CCD_PIXEL_SIZE_Y"),
            bits_per_pixel=round(info.number("CCD_BITSPERPIXEL")),
        )

    @property
    def temperature(self) -> float | None:
        if not self.has("CCD_TEMPERATURE"):
            return None
        return self.prop("CCD_TEMPERATURE").number("CCD_TEMPERATURE_VALUE")

    @property
    def can_cool(self) -> bool:
        """Whether the sensor temperature can be set: uncooled cameras report it read-only."""
        return (
            self.has("CCD_TEMPERATURE")
            and self.prop("CCD_TEMPERATURE").perm is not Permission.READ_ONLY
        )

    @property
    def cooler_on(self) -> bool | None:
        if not self.has("CCD_COOLER"):
            return None
        return self.prop("CCD_COOLER").switch("COOLER_ON")

    @property
    def cooler_power(self) -> float | None:
        """Cooler duty as the driver reports it (units vary by driver)."""
        if not self.has("CCD_COOLER_POWER"):
            return None
        return self.prop("CCD_COOLER_POWER").number("CCD_COOLER_VALUE")

    @property
    def temperature_ramp(self) -> float | None:
        """Maximum cooling or warming rate in °C per minute; 0 means unlimited."""
        if not self.has("CCD_TEMP_RAMP"):
            return None
        return self.prop("CCD_TEMP_RAMP").number("RAMP_SLOPE")

    @property
    def exposing(self) -> bool:
        return self.prop("CCD_EXPOSURE").state is PropertyState.BUSY

    @property
    def exposure_remaining(self) -> float | None:
        """Seconds left in the current exposure, as counted down by the driver."""
        prop = self.prop("CCD_EXPOSURE")
        return prop.number("CCD_EXPOSURE_VALUE") if prop.state is PropertyState.BUSY else None

    @property
    def exposure_range(self) -> Range | None:
        """Seconds the driver accepts (bias frames use the shortest)."""
        element = self._control((("CCD_EXPOSURE", "CCD_EXPOSURE_VALUE"),))
        return Range(element.min, element.max) if element is not None else None

    @property
    def gain(self) -> float | None:
        element = self._control(_GAIN)
        return element.value if element is not None else None

    @property
    def gain_range(self) -> Range | None:
        element = self._control(_GAIN)
        return Range(element.min, element.max) if element is not None else None

    @property
    def offset(self) -> float | None:
        element = self._control(_OFFSET)
        return element.value if element is not None else None

    @property
    def offset_range(self) -> Range | None:
        element = self._control(_OFFSET)
        return Range(element.min, element.max) if element is not None else None

    @property
    def binning(self) -> tuple[int, int]:
        if not self.has("CCD_BINNING"):
            return (1, 1)
        prop = self.prop("CCD_BINNING")
        return (round(prop.number("HOR_BIN")), round(prop.number("VER_BIN")))

    @property
    def max_binning(self) -> int:
        if not self.has("CCD_BINNING"):
            return 1
        element = self.prop("CCD_BINNING").elements["HOR_BIN"]
        return round(element.max) if isinstance(element, NumberElement) else 1

    @property
    def region(self) -> Region:
        """The readout region; the whole sensor when the driver has no ``CCD_FRAME``."""
        if not self.has("CCD_FRAME"):
            sensor = self.sensor
            return Region(0, 0, sensor.width, sensor.height)
        prop = self.prop("CCD_FRAME")
        return Region(
            round(prop.number("X")),
            round(prop.number("Y")),
            round(prop.number("WIDTH")),
            round(prop.number("HEIGHT")),
        )

    @property
    def bayer_pattern(self) -> str | None:
        """Color filter array (e.g. ``RGGB``) of a color sensor; ``None`` for mono."""
        if not self.has("CCD_CFA"):
            return None
        element = self.prop("CCD_CFA").elements.get("CFA_TYPE")
        if not isinstance(element, TextElement):
            return None
        return element.value.strip() or None

    @property
    def frame_type(self) -> FrameType:
        prop = self.prop("CCD_FRAME_TYPE")
        return next(t for t in FrameType if t.value in prop.elements and prop.switch(t.value))

    async def set_gain(self, value: float) -> None:
        await self._set_control(_GAIN, "gain", value)

    async def set_offset(self, value: float) -> None:
        await self._set_control(_OFFSET, "offset", value)

    async def set_region(self, region: Region | None) -> None:
        """Read out part of the sensor (unbinned pixels), or all of it with ``None``."""
        sensor = self.sensor
        if region is None:
            region = Region(0, 0, sensor.width, sensor.height)
        if (
            region.x < 0
            or region.y < 0
            or region.width < 1
            or region.height < 1
            or region.x + region.width > sensor.width
            or region.y + region.height > sensor.height
        ):
            raise ValueError(
                f"region {region} is outside the {sensor.width}x{sensor.height} sensor"
            )
        await self.command(
            "CCD_FRAME",
            {"X": region.x, "Y": region.y, "WIDTH": region.width, "HEIGHT": region.height},
        )

    async def set_temperature_ramp(self, degrees_per_minute: float) -> None:
        """Limit how fast the cooler changes temperature (0: as fast as it can)."""
        if not self.has("CCD_TEMP_RAMP"):
            raise DeviceError(f"{self.name} cannot ramp its temperature")
        await self.command("CCD_TEMP_RAMP", {"RAMP_SLOPE": degrees_per_minute})

    async def set_snooped_devices(
        self, *, mount: str = "", focuser: str = "", filter_wheel: str = ""
    ) -> None:
        """Tell the driver which devices to read FITS header values from (RA/Dec, focus, filter).

        Drivers default to the simulators' names; an empty name stops snooping.
        """
        if not self.has("ACTIVE_DEVICES"):
            return
        names = {
            "ACTIVE_TELESCOPE": mount,
            "ACTIVE_FOCUSER": focuser,
            "ACTIVE_FILTER": filter_wheel,
        }
        prop = self.prop("ACTIVE_DEVICES")
        values = {k: v for k, v in names.items() if k in prop.elements}
        await self.command("ACTIVE_DEVICES", values)

    async def set_optics(self, focal_length: float, aperture: float | None) -> None:
        """Focal length and aperture (mm) for the FITS header (``SCOPE_INFO``)."""
        if not self.has("SCOPE_INFO"):
            return
        values = {"FOCAL_LENGTH": focal_length, "APERTURE": aperture or 0.0}
        await self.command("SCOPE_INFO", values)

    async def set_temperature(self, celsius: float) -> None:
        """Set the cooler target. Returns at once: reaching it can take many minutes."""
        await self.client.send(self.name, "CCD_TEMPERATURE", {"CCD_TEMPERATURE_VALUE": celsius})

    async def set_cooler(self, on: bool) -> None:
        await self.client.send(self.name, "CCD_COOLER", {"COOLER_ON": on, "COOLER_OFF": not on})

    async def set_binning(self, x: int, y: int | None = None) -> None:
        await self.command("CCD_BINNING", {"HOR_BIN": x, "VER_BIN": y if y is not None else x})

    async def set_frame_type(self, frame_type: FrameType) -> None:
        values = {t.value: t is frame_type for t in FrameType}
        await self.command("CCD_FRAME_TYPE", values, done=lambda p: p.switch(frame_type.value))

    async def expose(self, seconds: float, frame_type: FrameType | None = None) -> Frame:
        """Take one exposure and return the image as delivered by the driver (FITS)."""
        await self._prepare(seconds, frame_type)
        await self.set_upload_mode("UPLOAD_CLIENT")
        images = self.images if self.images is not None else self.client
        if self.images is None:
            await self.client.enable_blob(self.name, BlobMode.ALSO, "CCD1")

        def frame(prop: Property) -> Frame | None:
            blob = prop.elements.get("CCD1") if prop.name == "CCD1" else None
            if not isinstance(blob, BlobElement) or blob.data is None:
                return None
            data, blob.data = blob.data, None  # do not keep tens of MB in the property mirror
            return Frame(data, blob.format, seconds)

        return await self._exposure(seconds, frame, images)

    def watch_frames(
        self, on_frame: Callable[[Frame], None], exposure: Callable[[], float]
    ) -> Callable[[], None]:
        """Call ``on_frame`` with each image the camera sends, whoever asked for it.

        For frames another INDI client (PHD2) takes; it needs the camera's image
        connection, with BLOBs enabled. ``exposure`` says how long they were. Returns
        a function that stops watching.
        """
        if self.images is None:
            raise DeviceError(f"{self.name}: watching frames needs its image connection")

        def on_event(event: IndiEvent) -> None:
            match event:
                case PropertyUpdated(property=prop) if (
                    prop.device == self.name and prop.name == "CCD1"
                ):
                    blob = prop.elements.get("CCD1")
                    if isinstance(blob, BlobElement) and blob.data is not None:
                        data, blob.data = blob.data, None  # not kept in the property mirror
                        on_frame(Frame(data, blob.format, exposure()))
                case _:
                    pass

        return self.images.add_listener(on_event)

    async def expose_to_file(
        self,
        seconds: float,
        frame_type: FrameType | None = None,
        *,
        directory: str,
        prefix: str = "NOCS_XXX",
    ) -> str:
        """Take one exposure that the driver saves itself (``UPLOAD_LOCAL``).

        Returns the path the driver wrote, as indiserver's host sees it. Nothing
        crosses the connection but that path, which is much cheaper than a BLOB
        when nocsd and indiserver share a filesystem (ADR 0012).
        """
        await self._prepare(seconds, frame_type)
        if not self.has("UPLOAD_SETTINGS"):
            raise DeviceError(f"{self.name} cannot save images itself")
        settings = self.prop("UPLOAD_SETTINGS")
        wanted = {"UPLOAD_DIR": directory, "UPLOAD_PREFIX": prefix}
        if any(settings.text(k) != v for k, v in wanted.items()):
            await self.command("UPLOAD_SETTINGS", wanted)
        await self.set_upload_mode("UPLOAD_LOCAL")

        def saved(prop: Property) -> str | None:
            if prop.name != "CCD_FILE_PATH" or prop.state is not PropertyState.OK:
                return None
            element = prop.elements.get("FILE_PATH")
            return element.value if isinstance(element, TextElement) and element.value else None

        # indiserver re-sends definitions when a client connects, and drivers reuse file
        # names, so an old path can come back mid-exposure: only an update counts.
        return await self._exposure(seconds, saved, self.client, updates_of="CCD_FILE_PATH")

    async def _prepare(self, seconds: float, frame_type: FrameType | None) -> None:
        if seconds < 0:
            raise ValueError("exposure must not be negative")
        if frame_type is not None and frame_type is not self.frame_type:
            await self.set_frame_type(frame_type)

    async def set_upload_mode(self, mode: str) -> None:
        """How the driver hands over frames: ``UPLOAD_CLIENT`` (BLOBs), ``UPLOAD_LOCAL``
        (saved by the driver) or ``UPLOAD_BOTH``.

        The mode belongs to the device, so it applies to every INDI client: in
        ``UPLOAD_LOCAL`` nobody gets BLOBs, PHD2 included (ADR 0012).
        """
        if not self.has("UPLOAD_MODE") or self.prop("UPLOAD_MODE").switch(mode):
            return
        values = {m: m == mode for m in self.prop("UPLOAD_MODE").elements}
        await self.command("UPLOAD_MODE", values, done=lambda p: p.switch(mode))

    async def _exposure[T](
        self,
        seconds: float,
        result_of: Callable[[Property], T | None],
        images: IndiClient,
        *,
        updates_of: str | None = None,
    ) -> T:
        """Start an exposure and wait for the update of this camera that ``result_of`` accepts.

        For property ``updates_of``, a definition counts only if the property did
        not exist yet: a definition of a known property is a re-send, not news.
        Fails on an ``Alert`` exposure or a lost connection, and when the camera stops
        answering (``Device.supervise``); a cancelled wait aborts the exposure on the
        camera too.
        """
        loop = asyncio.get_running_loop()
        result: asyncio.Future[T] = loop.create_future()
        known = updates_of is not None and self.has(updates_of)
        heard = loop.time()

        def on_event(event: IndiEvent) -> None:
            nonlocal heard
            if event_device(event) == self.name:
                heard = loop.time()
            if result.done():
                return
            match event:
                case PropertyDefined(property=prop) if known and prop.name == updates_of:
                    pass  # re-sent for some client's getProperties
                case PropertyUpdated(property=prop) | PropertyDefined(property=prop) if (
                    prop.device == self.name
                ):
                    if prop.name == "CCD_EXPOSURE" and prop.state is PropertyState.ALERT:
                        detail = f": {prop.message}" if prop.message else ""
                        result.set_exception(DeviceError(f"{self.name} exposure failed{detail}"))
                    elif (value := result_of(prop)) is not None:
                        result.set_result(value)
                case ConnectionLost(reason=reason):
                    result.set_exception(DeviceError(f"lost connection to indiserver: {reason}"))
                case _:
                    pass

        removers = [self.client.add_listener(on_event)]
        if images is not self.client:
            removers.append(images.add_listener(on_event))
        try:
            await self.client.send(self.name, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": seconds})
            return await self.supervise(
                result,
                loop.time() + seconds + DOWNLOAD_MARGIN,
                lambda: heard,
                f"{self.name}: no image {seconds + DOWNLOAD_MARGIN:g} s after start",
            )
        except asyncio.CancelledError:
            # Stop the camera too, so the next exposure does not have to wait for it.
            if self.exposing:
                await asyncio.shield(self._abort_quietly())
            raise
        finally:
            for remove in removers:
                remove()

    async def abort_exposure(self) -> None:
        await self.client.send(self.name, "CCD_ABORT_EXPOSURE", {"ABORT": True})

    async def _abort_quietly(self) -> None:
        with contextlib.suppress(ConnectionError, KeyError):
            await self.abort_exposure()

    def _control(self, places: tuple[tuple[str, str], ...]) -> NumberElement | None:
        for name, element_name in places:
            if self.has(name):
                element = self.prop(name).elements.get(element_name)
                if isinstance(element, NumberElement):
                    return element
        return None

    async def _set_control(
        self, places: tuple[tuple[str, str], ...], what: str, value: float
    ) -> None:
        for name, element_name in places:
            if self.has(name) and element_name in self.prop(name).elements:
                element = self._control(((name, element_name),))
                assert element is not None
                if not element.min <= value <= element.max:
                    raise ValueError(
                        f"{what} {value:g} is outside {element.min:g}..{element.max:g}"
                    )
                await self.command(name, {element_name: value})
                return
        raise DeviceError(f"{self.name} has no {what} control")
