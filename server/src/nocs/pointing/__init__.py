"""Where the rig points: solve frames of a camera, sync the mount, centre targets (phase 3)."""

from nocs.pointing.center import CenteringError, CenteringService, CenterOptions
from nocs.pointing.saved import SavedFrames, SkyFrames
from nocs.pointing.solve import (
    FrameSolve,
    Offset,
    PointingService,
    SolveOptions,
    offset,
)

__all__ = [
    "CenterOptions",
    "CenteringError",
    "CenteringService",
    "FrameSolve",
    "Offset",
    "PointingService",
    "SavedFrames",
    "SkyFrames",
    "SolveOptions",
    "offset",
]
