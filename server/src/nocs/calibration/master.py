"""A group's master: the median of a sequence group's darks, bias or flats.

Full size, in the sensor's own pixels (a colour sensor's Bayer mosaic kept, with its
``BAYERPAT``), as 16-bit integers: what a stacking program takes as a master. Flats
are neither bias-subtracted nor normalised; the header says what it is made of.

Runs in the imaging worker. The frames are read a strip of rows at a time, so a
master of 50 frames of 26 MP needs tens of megabytes, not gigabytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline

type MasterKind = Literal["dark", "bias", "flat"]

ROWS = 64
"""Rows read from every frame at once."""
STRUCTURAL = ("BZERO", "BSCALE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "NAXIS3", "EXTEND")


class GroupMasterError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class GroupMaster:
    path: str
    kind: MasterKind
    frames: int
    width: int
    height: int


def build(path: str, kind: MasterKind, frames: list[str]) -> GroupMaster:
    """Write the median of ``frames`` at ``path`` (replacing nothing: a new file)."""
    if not frames:
        raise GroupMasterError(f"no frames for a {kind} master")
    # Not memory-mapped: 16-bit frames carry BZERO, and a section reads only its rows.
    handles = [_fits.open(frame, memmap=False) for frame in frames]
    try:
        hdus = [h[0] for h in handles]
        shape = _shape(hdus[0].header)
        if shape is None:
            raise GroupMasterError(f"{Path(frames[0]).name} is not a single image")
        height, width = shape
        for hdu, frame in zip(hdus, frames, strict=True):
            if _shape(hdu.header) != shape:
                raise GroupMasterError(f"{Path(frame).name} is not {width}x{height}")
        master = np.empty((height, width), dtype=np.uint16)
        for start in range(0, height, ROWS):
            stop = min(start + ROWS, height)
            strips = np.stack(
                [np.asarray(hdu.section[start:stop, :], dtype=np.float32) for hdu in hdus]
            )
            median = np.median(strips, axis=0)
            master[start:stop] = np.clip(np.rint(median), 0, 65535).astype(np.uint16)
        header = hdus[0].header.copy()
    finally:
        for h in handles:
            h.close()
    for keyword in STRUCTURAL:
        header.remove(keyword, ignore_missing=True, remove_all=True)
    header["IMAGETYP"] = (f"Master {kind.capitalize()}", "median of a NOCS sequence group")
    header["NCOMBINE"] = (len(frames), "frames in the master")
    if kind == "flat":
        header["CALSTAT"] = ("none", "neither bias-subtracted nor normalised")
    hdu = _fits.PrimaryHDU(data=master, header=header)
    hdu.writeto(path)
    return GroupMaster(path, kind, len(frames), width, height)


def _shape(header: Any) -> tuple[int, int] | None:
    """(height, width) of a single 2-D image, from its header (not its data)."""
    if header.get("NAXIS") != 2:
        return None
    return int(header["NAXIS2"]), int(header["NAXIS1"])
