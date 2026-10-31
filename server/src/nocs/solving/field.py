"""The sky a camera sees through its optical train: pixel scale and field of view."""

from __future__ import annotations

import math
from dataclasses import dataclass

from nocs.devices import SensorInfo
from nocs.equipment import Optics

ARCSEC_PER_RADIAN = 180 / math.pi * 3600


@dataclass(frozen=True, slots=True)
class FieldOfView:
    focal_length: float
    """Effective focal length (with the reducer or barlow), mm."""
    scale: float
    """Arcseconds per (binned) pixel."""
    width: float
    """Degrees across the frame (its x axis)."""
    height: float
    """Degrees along the frame's y axis."""


def field_of_view(
    optics: Optics, sensor: SensorInfo, binning: int = 1, size: tuple[int, int] | None = None
) -> FieldOfView | None:
    """What a frame of ``size`` binned pixels covers (the whole sensor by default).

    ``None`` while the sensor is not known yet (drivers report 0x0 at first).
    """
    focal = optics.focal_length * optics.reducer
    if sensor.pixel_size_x <= 0 or sensor.width <= 0 or sensor.height <= 0:
        return None
    width, height = size or (sensor.width // binning, sensor.height // binning)
    pixel = sensor.pixel_size_x * binning / 1000  # mm
    scale = pixel / focal * ARCSEC_PER_RADIAN
    return FieldOfView(
        focal_length=focal,
        scale=scale,
        width=width * scale / 3600,
        height=height * scale / 3600,
    )
