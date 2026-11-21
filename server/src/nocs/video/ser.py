"""SER video files (what INDI's stream recorder writes): their header.

The format: a 178-byte little-endian header, the frames, then an optional trailer of
timestamps. https://grischa-hahn.hier-im-netz.com/astro/ser/
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

HEADER = 178
_FIELDS = struct.Struct("<14s7i")
COLORS = {0: "mono", 8: "RGGB", 9: "GRBG", 10: "GBRG", 11: "BGGR", 100: "RGB", 101: "BGR"}


class SerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SerHeader:
    width: int
    height: int
    depth: int
    """Bits per pixel and channel."""
    color: str
    """``mono``, a Bayer pattern (``RGGB``…), ``RGB`` or ``BGR``."""
    frames: int

    @property
    def frame_bytes(self) -> int:
        channels = 3 if self.color in ("RGB", "BGR") else 1
        return self.width * self.height * channels * (2 if self.depth > 8 else 1)


def read_header(path: Path) -> SerHeader:
    """The header of a SER file (blocks)."""
    with path.open("rb") as f:
        data = f.read(HEADER)
    if len(data) < HEADER:
        raise SerError(f"{path.name} is not a SER file")
    # The format says LUCAM-RECORDER; INDI writes INDI-RECORDER.
    file_id, _, color, _, width, height, depth, frames = _FIELDS.unpack_from(data)
    if not file_id.rstrip(b"\0").endswith(b"RECORDER") or width <= 0 or height <= 0:
        raise SerError(f"{path.name} is not a SER file")
    if not 1 <= depth <= 16 or frames < 0:
        raise SerError(f"{path.name} has a broken header")
    return SerHeader(width, height, depth, COLORS.get(color, "mono"), frames)


def frames_written(path: Path, header: SerHeader) -> int:
    """Frames in the file so far, from its size: the header's count is written last."""
    size = path.stat().st_size
    return max(0, (size - HEADER) // header.frame_bytes) if header.frame_bytes else 0
