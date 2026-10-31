"""Typed device facades (camera, mount, focuser, filter wheel) over the INDI client."""

from nocs.devices.base import Device, DeviceError, DeviceInterface, device_interfaces
from nocs.devices.camera import Camera, Frame, FrameType, SensorInfo
from nocs.devices.filter_wheel import FilterWheel
from nocs.devices.focuser import Focuser
from nocs.devices.mount import (
    STOPPED,
    AltitudeLimits,
    Coordinates,
    Direction,
    Horizontal,
    Location,
    MeridianLimits,
    Motion,
    Mount,
    PierSide,
)

__all__ = [
    "STOPPED",
    "AltitudeLimits",
    "Camera",
    "Coordinates",
    "Device",
    "DeviceError",
    "DeviceInterface",
    "Direction",
    "FilterWheel",
    "Focuser",
    "Frame",
    "FrameType",
    "Horizontal",
    "Location",
    "MeridianLimits",
    "Motion",
    "Mount",
    "PierSide",
    "SensorInfo",
    "device_interfaces",
]
