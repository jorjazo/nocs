from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from nocs.devices.base import Device, DeviceError, DeviceInterface
from nocs.indi import (
    BlobElement,
    BlobMode,
    ConnectionLost,
    IndiEvent,
    PropertyState,
    PropertyUpdated,
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


class Camera(Device):
    """Main imaging sensor of a camera (``CCD_*`` properties, image in ``CCD1``)."""

    INTERFACE = DeviceInterface.CCD
    REQUIRED = ("CCD_INFO", "CCD_EXPOSURE", "CCD_FRAME_TYPE", "CCD1")

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
    def cooler_on(self) -> bool | None:
        if not self.has("CCD_COOLER"):
            return None
        return self.prop("CCD_COOLER").switch("COOLER_ON")

    @property
    def exposing(self) -> bool:
        return self.prop("CCD_EXPOSURE").state is PropertyState.BUSY

    @property
    def frame_type(self) -> FrameType:
        prop = self.prop("CCD_FRAME_TYPE")
        return next(t for t in FrameType if t.value in prop.elements and prop.switch(t.value))

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
        if seconds < 0:
            raise ValueError("exposure must not be negative")
        if frame_type is not None and frame_type is not self.frame_type:
            await self.set_frame_type(frame_type)
        await self.client.enable_blob(self.name, BlobMode.ALSO, "CCD1")

        loop = asyncio.get_running_loop()
        result: asyncio.Future[Frame] = loop.create_future()

        def on_event(event: IndiEvent) -> None:
            if result.done():
                return
            match event:
                case PropertyUpdated(property=prop) if prop.device == self.name:
                    if prop.name == "CCD_EXPOSURE" and prop.state is PropertyState.ALERT:
                        detail = f": {prop.message}" if prop.message else ""
                        result.set_exception(DeviceError(f"{self.name} exposure failed{detail}"))
                    elif prop.name == "CCD1":
                        blob = prop.elements.get("CCD1")
                        if isinstance(blob, BlobElement) and blob.data is not None:
                            result.set_result(Frame(blob.data, blob.format, seconds))
                case ConnectionLost(reason=reason):
                    result.set_exception(DeviceError(f"lost connection to indiserver: {reason}"))
                case _:
                    pass

        remove = self.client.add_listener(on_event)
        try:
            await self.client.send(self.name, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": seconds})
            async with asyncio.timeout(seconds + DOWNLOAD_MARGIN):
                return await result
        except TimeoutError as e:
            raise DeviceError(
                f"{self.name}: no image {seconds + DOWNLOAD_MARGIN:g} s after start"
            ) from e
        finally:
            remove()

    async def abort_exposure(self) -> None:
        await self.client.send(self.name, "CCD_ABORT_EXPOSURE", {"ABORT": True})
