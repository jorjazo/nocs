"""Typed device facades (camera, mount, focuser, filter wheel, power box, weather sensor)."""

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
from nocs.devices.power_box import Output, OutputKind, PowerBox, PowerInput, parse_output_id
from nocs.devices.weather import Environment, WeatherSensor, dew_point

__all__ = [
    "STOPPED",
    "AltitudeLimits",
    "Camera",
    "Coordinates",
    "Device",
    "DeviceError",
    "DeviceInterface",
    "Direction",
    "Environment",
    "FilterWheel",
    "Focuser",
    "Frame",
    "FrameType",
    "Horizontal",
    "Location",
    "MeridianLimits",
    "Motion",
    "Mount",
    "Output",
    "OutputKind",
    "PierSide",
    "PowerBox",
    "PowerInput",
    "SensorInfo",
    "WeatherSensor",
    "device_interfaces",
    "dew_point",
    "parse_output_id",
]
