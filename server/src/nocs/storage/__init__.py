"""Storage destinations, file layout, FITS headers and the frame catalog (ADR 0013)."""

from nocs.storage.catalog import FrameFilter, FrameRow, NightRow
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
    "FrameFacts",
    "FrameFilter",
    "FrameRow",
    "FrameUnavailableError",
    "Located",
    "NightRow",
    "SavedFrame",
    "StorageError",
    "StorageService",
]
