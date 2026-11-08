"""A frame offered to the live stack (ADR 0039).

Kept apart from the service, with no imaging imports, so the capture service can
build one without importing the stacking code (which imports the imaging pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Offered:
    """A light of the main camera, as the capture service hands it over."""

    path: Path
    owned: bool
    """The stacker's own copy (a link), to delete when done; else a saved frame's file."""
    bayer: str | None
    taken: datetime
    night: date
    exposure: float
    camera: str
    gain: float | None
    offset: float | None
    binning: int | None
    temperature: float | None
    filter: str | None
    target: str | None
    rotation: float | None = None
    stars: int | None = None
    hfr: float | None = None
    frame_id: int | None = None
