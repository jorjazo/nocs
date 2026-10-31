"""PHD2 settings rendered from the rig, in the format ``phd2 -l`` imports (ADR 0022).

Every line is ``key<TAB>1<TAB>value``: type ``1`` works for strings and numbers,
and PHD2 silently drops lines of other types. Importing a file replaces every
PHD2 profile, so the file holds one profile, numbered 1, whose name carries a
hash of the rest: PHD2 reporting that name means it runs these settings.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

PROFILE_ID = 1
SIDEREAL_ARCSEC_PER_S = 15.0
"""What PHD2's calibration assistant takes as the sidereal rate."""
DEFAULT_GUIDE_RATE = 0.5
"""Guide pulses at half the sidereal rate, when the mount does not say."""
CALIBRATION_DISTANCE = 25
"""Pixels the star should travel in each direction (PHD2's default)."""
CALIBRATION_STEPS = 12
"""Steps to cover that distance at declination 0 (PHD2's default)."""
MIN_CALIBRATION_STEPS = 6
DEFAULT_EXPOSURE_MS = 2000


@dataclass(frozen=True, slots=True)
class GuideRig:
    """What PHD2 needs to know about the rig."""

    camera: str
    """INDI device of the guide camera."""
    mount: str
    """INDI device of the mount, which receives the guide pulses."""
    pixel_size: float
    """Of the guide camera, unbinned, in µm."""
    focal_length: float
    """Of the guiding train, reducer included, in mm."""
    guide_rate: float | None
    """Of the mount, as a fraction of sidereal."""
    indi_host: str
    indi_port: int


@dataclass(frozen=True, slots=True)
class Phd2Settings:
    profile_name: str
    content: str


def pixel_scale(pixel_size: float, focal_length: float, binning: int = 1) -> float:
    """Arcseconds per pixel."""
    return 206.265 * pixel_size * binning / focal_length


def calibration_step(
    pixel_size: float,
    focal_length: float,
    guide_rate: float | None,
    *,
    binning: int = 1,
    declination: float = 0.0,
) -> int:
    """Calibration pulse in ms, as PHD2's calibration assistant computes it."""
    rate = guide_rate if guide_rate is not None and guide_rate > 0 else DEFAULT_GUIDE_RATE
    scale = pixel_scale(pixel_size, focal_length, binning)
    total = CALIBRATION_DISTANCE * scale / (SIDEREAL_ARCSEC_PER_S * rate)
    pulse = total / CALIBRATION_STEPS * 1000.0
    longest = total / MIN_CALIBRATION_STEPS * 1000.0
    pulse = min(longest, pulse / math.cos(math.radians(declination)))
    return math.ceil(pulse / 50.0) * 50


def render(rig: GuideRig, label: str) -> Phd2Settings:
    """The settings file for ``rig``; ``label`` names the NOCS profile in PHD2's."""
    for name, value in (("camera", rig.camera), ("mount", rig.mount), ("indi_host", rig.indi_host)):
        if not value or any(c in value for c in "\t\r\n"):
            raise ValueError(f"invalid {name} for PHD2: {value!r}")
    base = f"/profile/{PROFILE_ID}"
    step = calibration_step(rig.pixel_size, rig.focal_length, rig.guide_rate)
    entries: list[tuple[str, str | int | float]] = [
        (f"{base}/indi/INDIhost", rig.indi_host),
        (f"{base}/indi/INDIport", rig.indi_port),
        (f"{base}/indi/INDIcam", rig.camera),
        (f"{base}/indi/INDIcam_ccd", 0),
        (f"{base}/indi/INDImount", rig.mount),
        (f"{base}/camera/LastMenuChoice", f"INDI Camera [{rig.camera}]"),
        (f"{base}/scope/LastMenuChoice", f"INDI Mount [{rig.mount}]"),
        (f"{base}/camera/pixelsize", round(rig.pixel_size, 3)),
        (f"{base}/frame/focalLength", round(rig.focal_length)),
        (f"{base}/scope/CalibrationDuration", step),
        (f"{base}/scope/CalibrationDistance", CALIBRATION_DISTANCE),
        (f"{base}/AutoLoadCalibration", 1),
        (f"{base}/guider/multistar/enabled", 1),
        (f"{base}/ExposureDurationMs", DEFAULT_EXPOSURE_MS),
    ]
    body = "".join(f"{key}\t1\t{value}\n" for key, value in entries)
    digest = hashlib.sha256(body.encode()).hexdigest()[:8]
    name = f"NOCS {label} {digest}"
    content = (
        "PHD Config 1\n"
        "/ConfigVersion\t1\t2001\n"
        f"/currentProfile\t1\t{PROFILE_ID}\n"
        f"{base}/name\t1\t{name}\n"
        f"{body}"
    )
    return Phd2Settings(name, content)
