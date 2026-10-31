"""Storage destinations, file layout, FITS headers and the frame catalog (ADR 0013)."""

from nocs.storage.catalog import FocusRun, FrameFilter, FrameRow, NightRow, TemperatureSample
from nocs.storage.service import (
    AUTO,
    FrameFacts,
    FrameUnavailableError,
    Located,
    SavedFrame,
    StorageError,
    StorageService,
)

__all__ = [
    "AUTO",
    "FocusRun",
    "FrameFacts",
    "FrameFilter",
    "FrameRow",
    "FrameUnavailableError",
    "Located",
    "NightRow",
    "SavedFrame",
    "StorageError",
    "StorageService",
    "TemperatureSample",
]
