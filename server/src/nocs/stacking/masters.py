"""Calibration masters for the live stack, and applying them (ADR 0039).

A master is the per-pixel median of up to a few tens of raw frames from the
calibration library (ADR 0036), at the stack's resolution: each frame is reduced
as a light is (superpixel colour, mono whole or binned) before the median, which
is exact for darks and bias (both are linear), and near exact for flats (vignetting
and dust are smooth at two pixels).

Frames are read in strips with astropy's ``section``, so building a master from
twenty 26 MP frames holds one strip of each in memory, not twenty frames. A
master flat has each frame's bias (or dark flat) master subtracted and its level
divided out per channel first, so flats of different brightness (sky flats)
combine; the master is normalised to 1 per channel, so the flat's own tint does
not change the stack's colour.

Masters are internal: a FITS per master under nocsd's data directory, named by a
key of the frames they come from, built once and reused; never catalogued.

Without a dark, ``cosmetic`` removes hot pixels: a value far above the median of
its 3x3 neighbours and, above the sky, several times brighter than every one of them
(a star's core never is: its neighbours share its light).

Runs in the imaging worker: blocking and CPU-bound.
"""

from __future__ import annotations

import os
import tempfile
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import cv2
import numpy as np
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from numpy.typing import NDArray

from nocs.stacking import reduce

if TYPE_CHECKING:
    from nocs.imaging.pipeline import Mono16

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline

type Image = NDArray[np.float32]
type Kind = Literal["dark", "bias", "flat"]

STRIP_ROWS = 128
"""Raw rows read from every frame at a time (even, so Bayer cells stay whole)."""
LEVEL_BLOCKS = 32
"""Two-row blocks per frame from which a flat's level is measured."""
LEAST_FLAT = 0.05
"""A master flat never divides by less than this (dead or masked pixels)."""
HOT_SIGMA = 8.0
"""How far above its neighbours' median, in noise sigmas, a hot pixel stands."""
HOT_CONTRAST = 3.0
"""How many times further above the local sky than its brightest neighbour."""
OTHERS_SIGMA = 3.0
OTHERS_FRACTION = 0.05
"""On a colour image, the other channels of a hot pixel stay near their sky: within
``OTHERS_SIGMA`` sigmas, or this fraction of the pixel's own excess (in sigmas) for a
very hot one, whose neighbours' noise can reach a few sigmas. A star lifts them all."""
CACHED = 4
"""Masters held in memory in the worker; the least recently used goes first."""


class MasterError(Exception):
    """A master cannot be built from these frames."""


@dataclass(frozen=True, slots=True)
class Master:
    path: str
    kind: Kind
    frames: int


@dataclass(frozen=True, slots=True)
class Calibration:
    """What a stack applies to every frame: master files (paths), or a cosmetic pass."""

    dark: str | None = None
    """Dark (or bias) master, subtracted."""
    flat: str | None = None
    """Flat master, divided."""
    cosmetic: bool = True
    """Remove hot pixels when there is no dark (a bias does not remove them)."""
    bias: bool = False
    """The subtracted master is a bias, not a dark: hot pixels stay in the frame."""


_loaded: OrderedDict[str, Image] = OrderedDict()


def build(
    path: str,
    kind: Kind,
    frames: list[str],
    bayer: str | None,
    *,
    subtract: str | None = None,
) -> Master:
    """Write the master of ``frames`` at ``path`` unless it is already there.

    ``subtract``: for a flat, the master (bias or dark flat) taken off each frame
    before its level is measured.
    """
    target = Path(path)
    if target.is_file():
        frames_in = _valid(target)
        if frames_in is not None:
            return Master(path, kind, frames_in)
        target.unlink()  # cut short (a power cut while it was written): build it again
    if not frames:
        raise MasterError(f"no frames for a {kind} master")
    offset = load(subtract) if subtract is not None else None
    handles = [_fits.open(frame, memmap=False) for frame in frames]
    try:
        hdus = [h[0] for h in handles]
        height, width = _shape(hdus[0])
        for hdu, frame in zip(hdus, frames, strict=True):
            if _shape(hdu) != (height, width):
                raise MasterError(f"{Path(frame).name} is not {width}x{height}")
        pattern = _pattern(hdus[0], bayer)
        binned = reduce.binned(height * width, pattern)
        levels = [_level(hdu, pattern, binned, offset) for hdu in hdus] if kind == "flat" else None
        master = _median(hdus, pattern, binned, height, offset, levels)
    finally:
        for h in handles:
            h.close()
    if kind == "flat":
        for c in range(master.shape[2]):
            channel = master[..., c]
            channel /= np.float32(np.median(channel[::4, ::4]))
        np.maximum(master, np.float32(LEAST_FLAT), out=master)
    _write(target, master, kind, len(frames))
    return Master(path, kind, len(frames))


def load(path: str) -> Image:
    """A master as ``(height, width, channels)`` float32; kept in memory while used."""
    if path in _loaded:
        _loaded.move_to_end(path)
        return _loaded[path]
    with _fits.open(path, memmap=False) as hdul:
        planes = np.asarray(hdul[0].data, dtype=np.float32)
    image = np.ascontiguousarray(np.moveaxis(planes, 0, 2))
    _loaded[path] = image
    while len(_loaded) > CACHED:
        _loaded.popitem(last=False)
    return image


def forget() -> None:
    _loaded.clear()


def apply(image: Image, calibration: Calibration) -> int:
    """Calibrate a frame at the stack's resolution in place; returns the hot pixels
    the cosmetic pass removed (0 with a dark, which removes them itself)."""
    if calibration.dark is not None:
        dark = load(calibration.dark)
        _check(image, dark, "dark")
        image -= dark
    if calibration.flat is not None:
        flat = load(calibration.flat)
        _check(image, flat, "flat")
        image /= flat
    if calibration.cosmetic and (calibration.dark is None or calibration.bias):
        return cosmetic(image)
    return 0


def cosmetic(image: Image) -> int:
    """Replace hot pixels by the median of their neighbours, per channel, in place.

    A hot pixel stands far above its 3x3 neighbourhood and, above the local sky (a 5x5
    median, which follows vignetting), several times above its brightest neighbour.
    On a colour (superpixel) image it must also stand alone across channels: a hot
    photosite is one colour, while a star's light reaches every channel. Red and blue
    are one photosite in four, so a sharp star centred on one stands out of its own
    channel's neighbourhood like a hot pixel; only the other channels tell them apart.
    """
    ring = np.ones((3, 3), dtype=np.uint8)
    ring[1, 1] = 0
    channels = image.shape[2]
    excesses: list[Image] = []
    medians: list[Image] = []
    alone: list[NDArray[np.bool_]] = []
    for c in range(channels):
        channel = np.ascontiguousarray(image[..., c])
        median = np.asarray(cv2.medianBlur(channel, 3), dtype=np.float32)
        sky = np.asarray(cv2.medianBlur(channel, 5), dtype=np.float32)
        brightest = np.asarray(cv2.dilate(channel, ring), dtype=np.float32)
        excess = channel - median
        sample = excess[::4, ::4]
        sigma = max(float(np.median(np.abs(sample - np.median(sample)))) * 1.4826, 1e-3)
        alone.append(
            (excess > HOT_SIGMA * sigma) & (channel - sky > HOT_CONTRAST * (brightest - sky))
        )
        # How far each pixel stands above the local sky, in that channel's noise.
        excesses.append((channel - sky) / np.float32(sigma))
        medians.append(median)
    found = 0
    for c in range(channels):
        hot = alone[c]
        allowed = np.maximum(np.float32(OTHERS_SIGMA), np.float32(OTHERS_FRACTION) * excesses[c])
        for o in range(channels):
            if o != c:
                hot &= excesses[o] < allowed
        count = int(np.count_nonzero(hot))
        if count:
            channel = np.ascontiguousarray(image[..., c])
            channel[hot] = medians[c][hot]
            image[..., c] = channel
            found += count
    return found


def _shape(hdu: Any) -> tuple[int, int]:
    header = hdu.header
    if int(header.get("NAXIS", 0)) != 2:
        raise MasterError("expected 2-D frames")
    return int(header["NAXIS2"]), int(header["NAXIS1"])


def _pattern(hdu: Any, bayer: str | None) -> str | None:
    pattern = str(hdu.header.get("BAYERPAT", "")).strip() or bayer or ""
    return pattern.upper() or None


def _rows(hdu: Any, start: int, stop: int) -> Mono16:
    raw = np.asarray(hdu.section[start:stop, :])
    if raw.dtype == np.uint8:
        return raw.astype(np.uint16) * np.uint16(256)
    return np.clip(raw, 0, 65535).astype(np.uint16)


def _level(
    hdu: Any, pattern: str | None, binned: bool, offset: Image | None
) -> NDArray[np.float32]:
    """A flat's median per channel (after ``offset``), from blocks spread over it."""
    height = _shape(hdu)[0] // 2 * 2
    step = max(2, height // LEVEL_BLOCKS // 2 * 2)
    blocks: list[Image] = []
    for y in range(0, height, step):
        image = _reduce(_rows(hdu, y, y + 2), pattern, binned)
        if offset is not None:
            image -= offset[_reduced_rows(y, y + 2, pattern, binned)]
        blocks.append(image)
    sample = np.concatenate(blocks, axis=0)
    levels = np.median(sample.reshape(-1, sample.shape[2]), axis=0).astype(np.float32)
    if np.any(levels <= 0):
        raise MasterError("a flat with no light in it")
    return levels


def _median(
    hdus: list[Any],
    pattern: str | None,
    binned: bool,
    height: int,
    offset: Image | None,
    levels: list[NDArray[np.float32]] | None,
) -> Image:
    parts: list[Image] = []
    usable = height // 2 * 2 if pattern is not None or binned else height
    for y in range(0, usable, STRIP_ROWS):
        stop = min(y + STRIP_ROWS, usable)
        reduced: list[Image] = []
        for i, hdu in enumerate(hdus):
            image = _reduce(_rows(hdu, y, stop), pattern, binned)
            if offset is not None:
                image -= offset[_reduced_rows(y, stop, pattern, binned)]
            if levels is not None:
                image /= levels[i]
            reduced.append(image)
        parts.append(np.median(np.stack(reduced), axis=0).astype(np.float32))
    return np.ascontiguousarray(np.concatenate(parts, axis=0))


def _reduce(raw: Mono16, pattern: str | None, binned: bool) -> Image:
    """``stack.to_stack_image`` for a strip: the strip alone is too small to tell
    whether the frame bins, so the caller says."""
    if pattern is None and binned:
        h, w = raw.shape[0] // 2 * 2, raw.shape[1] // 2 * 2
        cells = raw[:h, :w].reshape(h // 2, 2, w // 2, 2).sum(axis=(1, 3), dtype=np.float32)
        return (cells * np.float32(0.25))[..., np.newaxis]
    return reduce.to_stack_image(raw, pattern)


def _reduced_rows(start: int, stop: int, pattern: str | None, binned: bool) -> slice:
    if pattern is not None or binned:
        return slice(start // 2, stop // 2)
    return slice(start, stop)


def _check(image: Image, master: Image, kind: str) -> None:
    if master.shape != image.shape:
        raise MasterError(f"the {kind} master is {master.shape}, the frame {image.shape}")


def _valid(path: Path) -> int | None:
    """The frames in a master file, or None if it is not a whole master."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # "may have been truncated": that is the check
            with _fits.open(path, memmap=False) as hdul:
                header = hdul[0].header
                frames = int(header.get("NFRAMES", 0))
                shape = tuple(int(header.get(f"NAXIS{i}", 0)) for i in (1, 2, 3))
                expected = 4 * shape[0] * shape[1] * shape[2] if all(shape) else 0
                size = int(hdul.fileinfo(0)["datLoc"]) + expected
    except (OSError, ValueError, TypeError, IndexError):
        return None
    if frames <= 0 or not expected or path.stat().st_size < int(size):
        return None
    return frames


def _write(target: Path, master: Image, kind: Kind, frames: int) -> None:
    hdu = _fits.PrimaryHDU(np.ascontiguousarray(np.moveaxis(master, 2, 0)))
    hdu.header["IMAGETYP"] = f"Master {kind}"
    hdu.header["NFRAMES"] = (frames, "frames in the median")
    hdu.header["COMMENT"] = "NOCS live stacking master, at the stack's resolution"
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    os.close(fd)
    try:
        hdu.writeto(tmp, overwrite=True)
        # On disk before its name: renaming to a new name does not make ext4 flush it,
        # and a power cut would leave a short master that looks whole.
        with open(tmp, "rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
