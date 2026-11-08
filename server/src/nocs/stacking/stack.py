"""The live stack, held by the imaging worker process (ADR 0040).

Each frame is reduced to the stack's resolution (a colour frame by superpixel: one
RGB pixel per Bayer cell; a mono frame as it is, or 2x2 binned when large), its
stars registered on the first accepted frame's, warped onto it and added to a
running mean with per-pixel kappa-sigma rejection (Welford: mean, M2 and count per
pixel and channel). Whole frames are left out by a quality gate first.

The module keeps its stacks between calls: a ``ProcessPoolExecutor`` with one
worker keeps the process, and so this module's globals, alive. Each call names the
stack it expects; a stack the worker does not have (it was restarted) raises
``StackLostError`` rather than silently starting another.

Everything here is blocking and CPU-bound: it runs in the worker, never on the
event loop. Images are kept as float32 ``(height, width, channels)`` in OpenCV's
channel order (BGR) for colour.
"""

from __future__ import annotations

import math
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from numpy.typing import NDArray

from nocs.imaging.pipeline import PREVIEW_WIDTH, apply_mtf, load, mtf_parameters, write_jpeg
from nocs.stacking import masters
from nocs.stacking.masters import Calibration
from nocs.stacking.reduce import CELLS, FrameError, binned, luminance, to_stack_image
from nocs.stacking.register import (
    Registration,
    RegistrationError,
    Stars,
    Transform,
    find_stars,
    register,
)

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline

__all__ = ["FrameError", "luminance", "to_stack_image"]

KAPPA = 3.0
"""A value further than this many standard deviations from a pixel's mean is not added."""
REJECT_FROM = 8
"""Values a pixel must have before a new one can be rejected: fewer give a spread too
noisy to judge by (with 5, ~5 % of good values went)."""
LEAST_NOISE = 1.0
"""ADU: the noise floor of the rejection when a frame's own noise reads lower."""
SCALE_LIMITS = (1 / 3, 3.0)
"""How far a frame's brightness may be scaled to match the reference's (haze, altitude)."""
STRIP_ROWS = 32
"""Rows updated at a time, so the arrays of a strip stay in the CPU's cache."""
GATE_FROM = 3
"""Accepted frames before the quality gate compares a frame with them."""
GATE_STARS = 0.5
"""A frame with fewer stars than this fraction of the stack's median is left out."""
GATE_HFR = 1.5
"""A frame with an HFR above this many times the stack's median is left out."""
COVERAGE = 0.5
"""The rendered stack is cropped to where at least this fraction of its frames cover."""
MAX_STACKS = 4
"""Stacks held at once (a mono camera keeps one per filter); the oldest goes first."""
MAX_BYTES = 420 * 2**20
"""Memory the stacks may hold together (two 26 MP colour stacks); the oldest go first."""

type Image = NDArray[np.float32]


class StackLostError(Exception):
    """The worker does not hold the stack asked for (it was restarted, or dropped it)."""


class EmptyStackError(Exception):
    """The stack has no frame yet (or no part of it is covered): nothing to show or save."""


@dataclass(frozen=True, slots=True)
class Look:
    """How the linear stack is turned into a picture."""

    background: float = 0.25
    """Where the stretch puts the sky's median, 0..1."""
    shadows: float = -2.8
    """Black point, in MADs from the median (more negative keeps more of the faint end)."""
    saturation: float = 1.0
    """Colour gain around the luminance; 1 leaves colours as stretched."""
    linked: bool = False
    """One stretch for every channel (keeps a colour balance), else one per channel
    (also neutralises the sky's colour)."""


@dataclass(frozen=True, slots=True)
class Rendered:
    path: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Added:
    """What happened to a frame offered to a stack."""

    accepted: bool
    reason: str | None
    """Why the frame was left out; None when accepted."""
    frames: int
    """Frames in the stack now."""
    rejected: int
    """Frames left out of it so far."""
    shift: tuple[float, float] | None = None
    """Pixels (of the stack) the frame was moved by, at its centre."""
    rotation: float | None = None
    """Degrees the frame was turned by."""
    stars: int | None = None
    """Stars paired with the reference."""
    rms: float | None = None
    clipped: float | None = None
    hot_pixels: int | None = None
    """Hot pixels the cosmetic pass removed from the frame (no dark)."""
    """Fraction of the frame's values the kappa-sigma rejection left out."""
    scale: float | None = None
    """Factor the frame's brightness was multiplied by to match the reference's."""
    preview: Rendered | None = None
    seconds: float = 0.0
    steps: dict[str, float] = field(default_factory=dict[str, float])
    """Seconds per step, for the benchmark and the log."""


class Stack:
    """A running stack: the reference's stars and per-pixel mean, M2 and count."""

    def __init__(self) -> None:
        self.reference: Stars | None = None
        self.pattern: str | None = None
        self.bottom_up = False
        self.binned = False
        self.mean: Image | None = None
        self.m2: Image | None = None
        self.count: NDArray[np.uint16] | None = None
        self.frames = 0
        self.rejected = 0
        self.star_counts: list[int] = []
        self.hfrs: list[float] = []
        self.calibration = Calibration(cosmetic=False)
        self.background: NDArray[np.float32] | None = None
        """The reference's sky level per channel: every frame is matched to it."""

    @property
    def nbytes(self) -> int:
        return sum(a.nbytes for a in (self.mean, self.m2, self.count) if a is not None)

    @property
    def shape(self) -> tuple[int, ...] | None:
        return None if self.mean is None else self.mean.shape

    def gate(self, stars: int | None, hfr: float | None) -> str | None:
        """Why a frame with these metrics should be left out, if it should."""
        if self.frames < GATE_FROM:
            return None
        if stars is not None and self.star_counts:
            median = float(np.median(self.star_counts))
            if stars < GATE_STARS * median:
                return f"too few stars ({stars}, the stack's median is {median:.0f})"
        if hfr is not None and self.hfrs:
            median = float(np.median(self.hfrs))
            if hfr > GATE_HFR * median:
                return f"stars too large (HFR {hfr:.2f}, the stack's median is {median:.2f})"
        return None

    def accumulate(self, image: Image, noise: NDArray[np.float32]) -> float:
        """Add a frame already matched to the reference and on its geometry (NaN where it
        has no data); ``noise`` is its sky's noise per channel. Returns the fraction of
        its values rejected."""
        if self.mean is None or self.m2 is None or self.count is None:
            self.mean = np.zeros(image.shape, dtype=np.float32)
            self.m2 = np.zeros(image.shape, dtype=np.float32)
            self.count = np.zeros(image.shape, dtype=np.uint16)
        # A pixel's spread from a few values is itself noisy and, as rejected values do
        # not enter it, shrinks: never judge a value against less than the frame's noise.
        floor = np.maximum(noise, np.float32(LEAST_NOISE)).astype(np.float32) * np.float32(KAPPA)
        rejected = 0
        valid = 0
        for y in range(0, image.shape[0], STRIP_ROWS):
            rows = slice(y, y + STRIP_ROWS)
            x, mean, m2, count = image[rows], self.mean[rows], self.m2[rows], self.count[rows]
            n = count.astype(np.float32)
            ok = np.isfinite(x)
            valid += int(np.count_nonzero(ok))
            delta = np.where(ok, x - mean, np.float32(0))
            limit = np.sqrt(m2 / np.maximum(n - 1, 1)) * np.float32(KAPPA)
            np.maximum(limit, floor, out=limit)
            outlier = ok & (n >= REJECT_FROM) & (np.abs(delta) > limit)
            rejected += int(np.count_nonzero(outlier))
            ok &= ~outlier
            delta *= ok
            n += ok
            count += ok
            mean += delta / np.maximum(n, 1)
            m2 += delta * np.where(ok, x - mean, np.float32(0))
        self.frames += 1
        return rejected / valid if valid else 0.0


_stacks: dict[str, Stack] = {}


def add_frame(
    stack_id: str,
    fits_path: str,
    bayer: str | None,
    *,
    new: bool,
    stars: int | None = None,
    hfr: float | None = None,
    preview_path: str | None = None,
    look: Look | None = None,
    calibration: Calibration | None = None,
    width: int = PREVIEW_WIDTH,
) -> Added:
    """Offer a frame to stack ``stack_id`` (``new``: start it with this frame) and, if
    it went in and ``preview_path`` is given, render the stack there.

    ``stars`` and ``hfr`` are the frame's metrics from its preview, for the gate;
    ``calibration``, with ``new``, what every frame of the stack gets (masters must
    have been built).
    """
    start = time.perf_counter()
    if new:
        _stacks.pop(stack_id, None)
        while len(_stacks) >= MAX_STACKS:
            del _stacks[next(iter(_stacks))]
        _stacks[stack_id] = Stack()
        if calibration is not None:
            _stacks[stack_id].calibration = calibration
    stack = _get(stack_id)
    _stacks[stack_id] = _stacks.pop(stack_id)  # the most recently used goes last
    steps: dict[str, float] = {}

    def left_out(reason: str) -> Added:
        stack.rejected += 1
        return Added(
            False,
            reason,
            stack.frames,
            stack.rejected,
            seconds=round(time.perf_counter() - start, 3),
            steps=steps,
        )

    if (reason := stack.gate(stars, hfr)) is not None:
        return left_out(reason)

    t = time.perf_counter()
    data, header_bayer, bottom_up = load(fits_path)
    steps["load"] = _since(t)
    pattern = (header_bayer or bayer or "").upper() or None
    t = time.perf_counter()
    image = to_stack_image(data, pattern)
    is_binned = binned(data.size, pattern)
    del data
    steps["reduce"] = _since(t)
    if stack.reference is None:
        stack.pattern, stack.bottom_up, stack.binned = pattern, bottom_up, is_binned
    elif pattern != stack.pattern or bottom_up != stack.bottom_up or image.shape != stack.shape:
        raise FrameError("the frame does not match the stack (camera, size or Bayer pattern)")
    t = time.perf_counter()
    hot = masters.apply(image, stack.calibration)
    steps["calibrate"] = _since(t)

    t = time.perf_counter()
    found = find_stars(luminance(image))
    steps["stars"] = _since(t)

    registration: Registration
    if stack.reference is None:
        if len(found) < 6:
            return left_out(f"too few stars to start a stack ({len(found)})")
        registration = Registration(Transform.identity(), len(found), 0.0)
    else:
        t = time.perf_counter()
        try:
            registration = register(found, stack.reference)
        except RegistrationError as error:
            return left_out(str(error))
        steps["register"] = _since(t)

    transform = registration.transform
    t = time.perf_counter()
    background, noise = sky(image)
    if stack.background is None:
        stack.background = background
    scale = 1.0
    if registration.flux_ratio is not None:
        scale = min(max(registration.flux_ratio, SCALE_LIMITS[0]), SCALE_LIMITS[1])
    # Matched to the reference: its sky level, and its stars' brightness.
    image -= background
    image *= np.float32(scale)
    image += stack.background
    if stack.reference is not None:
        image = warp(image, transform, channel_offsets(pattern, image.shape[2]))
    steps["warp"] = _since(t)
    t = time.perf_counter()
    clipped = stack.accumulate(image, (noise * np.float32(scale)).astype(np.float32))
    del image
    steps["accumulate"] = _since(t)
    _evict(keep=stack_id)
    if stack.reference is None:
        stack.reference = found
    if stars is not None:
        stack.star_counts.append(stars)
    if hfr is not None:
        stack.hfrs.append(hfr)

    preview = None
    if preview_path is not None:
        t = time.perf_counter()
        try:
            preview = _render(stack, preview_path, look or Look(), width)
        except EmptyStackError:
            preview = None  # too little covered yet: the frame went in all the same
        steps["render"] = _since(t)
    assert stack.shape is not None
    centre = np.array([[stack.shape[1] / 2, stack.shape[0] / 2]])
    moved = transform.apply(centre) - centre
    return Added(
        True,
        None,
        stack.frames,
        stack.rejected,
        shift=(round(float(moved[0, 0]), 2), round(float(moved[0, 1]), 2)),
        rotation=round(transform.rotation, 3),
        stars=registration.stars,
        rms=registration.rms,
        clipped=round(clipped, 5),
        hot_pixels=hot
        if stack.calibration.cosmetic and (stack.calibration.dark is None or stack.calibration.bias)
        else None,
        scale=round(scale, 4),
        preview=preview,
        seconds=round(time.perf_counter() - start, 3),
        steps=steps,
    )


def render(stack_id: str, preview_path: str, look: Look, width: int = PREVIEW_WIDTH) -> Rendered:
    """Render the stack as it stands (a new look, without a new frame)."""
    return _render(_get(stack_id), preview_path, look, width)


def save(
    stack_id: str,
    fits_path: str,
    jpeg_path: str,
    look: Look,
    header: Mapping[str, str | int | float | bool | None],
) -> Rendered:
    """Write the linear stack as a float32 FITS (colour as R, G, B planes; NaN where no
    frame covers) and a full-size JPEG of it; returns the JPEG."""
    stack = _get(stack_id)
    if stack.mean is None or stack.count is None:
        raise EmptyStackError("the stack has no frames")
    target = Path(fits_path)
    if target.exists():
        # Renaming over a file makes ext4 flush it first: seconds on the Pi's microSD.
        raise FileExistsError(f"{target} exists: a stack is saved under a new name")
    data = np.where(stack.count > 0, stack.mean, np.float32(np.nan))
    planes = np.ascontiguousarray(np.moveaxis(data[..., ::-1], 2, 0))  # BGR -> R, G, B
    hdu = _fits.PrimaryHDU(planes[0] if planes.shape[0] == 1 else planes)
    hdu.header["ROWORDER"] = "BOTTOM-UP" if stack.bottom_up else "TOP-DOWN"
    hdu.header["NCOMBINE"] = (stack.frames, "frames in the stack")
    if stack.pattern is not None:
        hdu.header["HISTORY"] = f"superpixel debayer of {stack.pattern} frames: R, G, B planes"
    elif stack.binned:
        hdu.header["HISTORY"] = "frames binned 2x2"
    for key, value in header.items():
        if value is not None:
            hdu.header[key] = value
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    os.close(fd)
    try:
        hdu.writeto(tmp, overwrite=True)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    height, width = data.shape[:2]
    return _render(stack, jpeg_path, look, max(width, height))


def drop(stack_id: str) -> None:
    """Forget a stack and free its memory."""
    _stacks.pop(stack_id, None)


def drop_all() -> None:
    _stacks.clear()


def channel_offsets(pattern: str | None, channels: int) -> list[tuple[float, float]]:
    """Where each channel of a stack image samples the sky, relative to the centre of its
    pixel, in stack pixels (x, y): in a superpixel, red and blue sit in opposite corners
    of the Bayer cell, green (the mean of two) at its centre."""
    if pattern is None:
        return [(0.0, 0.0)] * channels
    r, g1, g2, b = CELLS[pattern]

    def offset(*cells: tuple[int, int]) -> tuple[float, float]:
        row = sum(c[0] for c in cells) / len(cells)
        column = sum(c[1] for c in cells) / len(cells)
        return (column - 0.5) / 2, (row - 0.5) / 2

    return [offset(b), offset(g1, g2), offset(r)]  # OpenCV's order: B, G, R


def warp(
    image: Image, transform: Transform, offsets: list[tuple[float, float]] | None = None
) -> Image:
    """``image`` moved onto the reference by ``transform``; NaN where it has no data.

    ``offsets`` (``channel_offsets``) moves each channel by its own place in the Bayer
    cell: a turned frame (a meridian flip) would otherwise put red and blue half a pixel
    off the green, the opposite way each."""
    height, width, channels = image.shape
    matrix = transform.matrix()
    if offsets is None or not any(dx or dy for dx, dy in offsets):
        moved = cv2.warpAffine(
            image,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(math.nan, math.nan, math.nan, math.nan),
        )
        return np.asarray(moved, dtype=np.float32).reshape(height, width, channels)
    out = np.empty_like(image)
    linear = matrix[:, :2]
    for c, (dx, dy) in enumerate(offsets):
        # A channel sample at q is the sky at q + d: it goes to T(q + d) - d.
        d = np.array([dx, dy])
        shifted = matrix.copy()
        shifted[:, 2] += linear @ d - d
        out[..., c] = cv2.warpAffine(
            np.ascontiguousarray(image[..., c]),
            shifted,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=math.nan,
        )
    return out


def sky(image: Image) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """The sky level (median) and noise (MAD as sigma) of each channel, from a sample."""
    sample = image[::4, ::4].reshape(-1, image.shape[2])
    level = np.nanmedian(sample, axis=0)
    noise = np.nanmedian(np.abs(sample - level), axis=0) * 1.4826
    return level.astype(np.float32), noise.astype(np.float32)


def _evict(keep: str) -> None:
    """Drop the least recently used stacks while they hold more than ``MAX_BYTES``."""
    while sum(s.nbytes for s in _stacks.values()) > MAX_BYTES:
        oldest = next((k for k in _stacks if k != keep), None)
        if oldest is None:
            return
        del _stacks[oldest]


def _render(stack: Stack, path: str, look: Look, width: int) -> Rendered:
    if stack.mean is None or stack.count is None or stack.frames == 0:
        raise EmptyStackError("the stack has no frames")
    least = max(1, math.ceil(stack.frames * COVERAGE))
    covered = stack.count.min(axis=2) >= least
    rows, columns = np.flatnonzero(covered.any(axis=1)), np.flatnonzero(covered.any(axis=0))
    if rows.size == 0 or columns.size == 0:
        raise EmptyStackError("no part of the stack is covered")
    box = (slice(rows[0], rows[-1] + 1), slice(columns[0], columns[-1] + 1))
    crop = stack.mean[box]
    inside = covered[box]
    if not inside.all():
        # The corners a turned frame leaves uncovered show as sky, not black, and do not
        # pull the stretch's statistics down.
        level = np.median(crop[inside], axis=0).astype(np.float32)
        crop = np.where(inside[..., np.newaxis], crop, level)
    height, across = crop.shape[:2]
    if across > width:
        size = (width, max(1, round(height * width / across)))
        crop = np.asarray(cv2.resize(crop, size, interpolation=cv2.INTER_AREA), dtype=np.float32)
        crop = crop.reshape(size[1], size[0], stack.mean.shape[2])
    picture = stretch(crop / np.float32(65535.0), look)
    if stack.bottom_up:
        picture = np.ascontiguousarray(picture[::-1])
    write_jpeg(Path(path), picture)
    return Rendered(path, int(picture.shape[1]), int(picture.shape[0]))


def stretch(data: Image, look: Look) -> NDArray[np.uint8]:
    """A linear image normalised to 0..1 as 8 bits, by the look's midtones stretch."""
    channels = data.shape[2]
    sample = data[::2, ::2]
    out = np.empty(data.shape, dtype=np.float32)
    if look.linked or channels == 1:
        shadows, midtones = mtf_parameters(luminance(sample), look.background, look.shadows)
        for c in range(channels):
            out[..., c] = apply_mtf(data[..., c], shadows, midtones)
    else:
        for c in range(channels):
            shadows, midtones = mtf_parameters(sample[..., c], look.background, look.shadows)
            out[..., c] = apply_mtf(data[..., c], shadows, midtones)
    if channels == 3 and look.saturation != 1.0:
        grey = luminance(out)[..., np.newaxis]
        out = np.clip(grey + np.float32(look.saturation) * (out - grey), 0.0, 1.0)
    picture = (out * 255).astype(np.uint8)
    return picture[..., 0] if channels == 1 else picture


def _get(stack_id: str) -> Stack:
    try:
        return _stacks[stack_id]
    except KeyError:
        raise StackLostError(f"the worker has no stack {stack_id}") from None


def _since(start: float) -> float:
    return round(time.perf_counter() - start, 4)
