"""Where the rig points: solve frames of a camera and sync the mount (phase 3)."""

from nocs.pointing.solve import (
    FrameSolve,
    Offset,
    PointingService,
    SolveOptions,
    offset,
)

__all__ = ["FrameSolve", "Offset", "PointingService", "SolveOptions", "offset"]
