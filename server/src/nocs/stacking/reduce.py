"""Frames reduced to the live stack's resolution (ADR 0039).

A colour frame becomes one RGB pixel per Bayer cell (superpixel), in OpenCV's
channel order (BGR); a mono frame stays whole, or is 2x2 binned when large.
Images are float32 ``(height, width, channels)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    # Only the type: importing nocs.imaging at run time imports the capture service.
    from nocs.imaging.pipeline import Mono16

type Image = NDArray[np.float32]

MONO_FULL_PIXELS = 16_000_000
"""Mono frames larger than this stack 2x2 binned."""

# Where each colour sits in a 2x2 Bayer cell (row, column), by the FITS pattern.
_CELLS: dict[str, tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]] = {
    #        R        G1       G2       B
    "RGGB": ((0, 0), (0, 1), (1, 0), (1, 1)),
    "BGGR": ((1, 1), (0, 1), (1, 0), (0, 0)),
    "GRBG": ((0, 1), (0, 0), (1, 1), (1, 0)),
    "GBRG": ((1, 0), (0, 0), (1, 1), (0, 1)),
}


def binned(pixels: int, pattern: str | None) -> bool:
    """Whether a frame of ``pixels`` stacks 2x2 binned (a large mono frame)."""
    return pattern is None and pixels > MONO_FULL_PIXELS


class FrameError(Exception):
    """A frame that cannot go into this stack at all (another size or kind of camera)."""


def to_stack_image(data: Mono16, pattern: str | None) -> Image:
    """A frame at the stack's resolution: superpixel BGR for a Bayer pattern; mono as it
    is, or 2x2 binned (mean) above ``MONO_FULL_PIXELS``."""
    if pattern is not None:
        try:
            r, g1, g2, b = _CELLS[pattern]
        except KeyError:
            raise FrameError(f"unsupported Bayer pattern {pattern}") from None
        h, w = data.shape[0] // 2 * 2, data.shape[1] // 2 * 2
        cells = data[:h, :w]
        out = np.empty((h // 2, w // 2, 3), dtype=np.float32)
        out[..., 0] = cells[b[0] :: 2, b[1] :: 2]
        np.add(cells[g1[0] :: 2, g1[1] :: 2], cells[g2[0] :: 2, g2[1] :: 2], out=out[..., 1])
        out[..., 1] *= np.float32(0.5)
        out[..., 2] = cells[r[0] :: 2, r[1] :: 2]
        return out
    if binned(data.size, None):
        h, w = data.shape[0] // 2 * 2, data.shape[1] // 2 * 2
        sums = data[:h, :w].reshape(h // 2, 2, w // 2, 2).sum(axis=(1, 3), dtype=np.float32)
        return (sums * np.float32(0.25))[..., np.newaxis]
    return data.astype(np.float32)[..., np.newaxis]


def luminance(image: Image) -> Image:
    return image[..., 0] if image.shape[2] == 1 else image.mean(axis=2, dtype=np.float32)
