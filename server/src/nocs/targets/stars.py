"""The stars the framing chart bundles: a Tycho-2 subset, queried around a point (ADR 0020).

The data file is a header line of JSON (format, sources, how values are stored) and
three columns of little-endian integers, compressed: declinations in ascending order
as differences from the previous star, right ascensions, magnitudes. Each 32-bit
column is stored byte plane by byte plane, which compresses far better than whole
integers. Positions are kept to 1e-4° (0.36″) and magnitudes to 0.05.
"""

from __future__ import annotations

import json
import lzma
import math
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from typing import cast

import numpy as np
import numpy.typing as npt

from nocs.targets.catalog import Source

FORMAT = 1
DATA_FILE = "tycho2.bin.xz"
MAGIC = b"NOCS-STARS\n"

POSITION_STEP = 1e-4
"""Degrees per unit of the stored positions."""
MAGNITUDE_STEP = 0.05
MAGNITUDE_ZERO = -2.0
"""The magnitude stored as 0."""

type Floats = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Star:
    ra: float
    """J2000, hours."""
    dec: float
    """J2000, degrees."""
    magnitude: float
    """Approximately Johnson V."""


@dataclass(frozen=True, slots=True)
class StarField:
    """Stars around a point, brightest first."""

    ra: Floats
    """J2000, hours."""
    dec: Floats
    """J2000, degrees."""
    magnitude: Floats
    truncated: bool
    """More stars matched than the limit asked for: only the brightest are here."""

    def __len__(self) -> int:
        return len(self.ra)


def encode(stars: Sequence[Star], sources: Sequence[Source], magnitude_limit: float) -> bytes:
    """The data file for these stars, the same bytes on every run."""
    count = len(stars)
    ra = np.fromiter((s.ra * 15 for s in stars), np.float64, count)
    dec = np.fromiter((s.dec for s in stars), np.float64, count)
    magnitude = np.fromiter((s.magnitude for s in stars), np.float64, count)
    ra_code = np.rint(ra / POSITION_STEP).astype(np.int64) % round(360 / POSITION_STEP)
    dec_code = np.rint((dec + 90) / POSITION_STEP).astype(np.int64)
    magnitude_code = np.rint((magnitude - MAGNITUDE_ZERO) / MAGNITUDE_STEP).astype(np.int64)
    if count and (magnitude_code.min() < 0 or magnitude_code.max() > 255):
        raise ValueError("magnitudes out of the stored range")
    order = np.lexsort((magnitude_code, ra_code, dec_code))
    dec_steps = np.diff(dec_code[order], prepend=0)
    header = {
        "format": FORMAT,
        "count": count,
        "magnitude_limit": magnitude_limit,
        "position_step": POSITION_STEP,
        "magnitude_step": MAGNITUDE_STEP,
        "magnitude_zero": MAGNITUDE_ZERO,
        "sources": [_source_dict(s) for s in sources],
    }
    payload = b"".join(
        [
            MAGIC,
            json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode() + b"\n",
            _planes(dec_steps.astype("<u4")),
            _planes(ra_code[order].astype("<u4")),
            magnitude_code[order].astype(np.uint8).tobytes(),
        ]
    )
    # xz carries no timestamp: the output is reproducible as it is.
    return lzma.compress(payload, preset=9 | lzma.PRESET_EXTREME)


def _planes(values: npt.NDArray[np.uint32]) -> bytes:
    return values.view(np.uint8).reshape(-1, 4).T.tobytes()


def _from_planes(data: bytes, count: int) -> npt.NDArray[np.uint32]:
    planes = np.frombuffer(data, np.uint8, 4 * count).reshape(4, count)
    return np.ascontiguousarray(planes.T).view("<u4").reshape(count)


def _source_dict(source: Source) -> dict[str, str]:
    return {
        "name": source.name,
        "version": source.version,
        "url": source.url,
        "license": source.license,
        "license_url": source.license_url,
        "attribution": source.attribution,
    }


class StarCatalog:
    def __init__(
        self,
        ra: Floats,
        dec: Floats,
        magnitude: Floats,
        sources: Sequence[Source] = (),
        magnitude_limit: float = math.inf,
    ) -> None:
        """Stars sorted by declination; RA in hours, Dec in degrees."""
        self.ra = ra
        self.dec = dec
        self.magnitude = magnitude
        self.sources = tuple(sources)
        self.magnitude_limit = magnitude_limit
        ra_rad, dec_rad = np.radians(ra * 15), np.radians(dec)
        cos_dec = np.cos(dec_rad)
        self._xyz = np.stack([cos_dec * np.cos(ra_rad), cos_dec * np.sin(ra_rad), np.sin(dec_rad)])

    def __len__(self) -> int:
        return len(self.ra)

    @classmethod
    def from_stars(cls, stars: Sequence[Star]) -> StarCatalog:
        ordered = sorted(stars, key=lambda s: s.dec)
        return cls(
            np.array([s.ra for s in ordered], np.float64),
            np.array([s.dec for s in ordered], np.float64),
            np.array([s.magnitude for s in ordered], np.float64),
        )

    @classmethod
    def load(cls) -> StarCatalog:
        """The stars bundled with nocsd."""
        data = resources.files("nocs.targets").joinpath("data", DATA_FILE).read_bytes()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> StarCatalog:
        payload = lzma.decompress(data)
        if not payload.startswith(MAGIC):
            raise ValueError("not a star file")
        end = payload.index(b"\n", len(MAGIC))
        header = cast(dict[str, object], json.loads(payload[len(MAGIC) : end]))
        if header.get("format") != FORMAT:
            raise ValueError(f"not a star file of format {FORMAT}")
        count = cast(int, header["count"])
        step = cast(float, header["position_step"])
        body = payload[end + 1 :]
        if len(body) != 9 * count:
            raise ValueError("star file truncated")
        dec_code = np.cumsum(_from_planes(body[: 4 * count], count), dtype=np.int64)
        ra_code = _from_planes(body[4 * count : 8 * count], count)
        magnitude_code = np.frombuffer(body[8 * count :], np.uint8, count)
        sources = [Source(**s) for s in cast(list[dict[str, str]], header["sources"])]
        magnitude_step = cast(float, header["magnitude_step"])
        magnitude_zero = cast(float, header["magnitude_zero"])
        return cls(
            ra=ra_code.astype(np.float64) * (step / 15),
            dec=dec_code.astype(np.float64) * step - 90,
            magnitude=magnitude_code.astype(np.float64) * magnitude_step + magnitude_zero,
            sources=sources,
            magnitude_limit=cast(float, header["magnitude_limit"]),
        )

    def near(
        self, ra: float, dec: float, radius: float, magnitude: float = math.inf, limit: int = 5000
    ) -> StarField:
        """Stars within `radius` degrees of a J2000 point (RA in hours) down to `magnitude`,
        the brightest `limit` of them, brightest first."""
        low = int(np.searchsorted(self.dec, dec - radius, side="left"))
        high = int(np.searchsorted(self.dec, dec + radius, side="right"))
        ra_rad, dec_rad = math.radians(ra * 15), math.radians(dec)
        centre = np.array(
            [
                math.cos(dec_rad) * math.cos(ra_rad),
                math.cos(dec_rad) * math.sin(ra_rad),
                math.sin(dec_rad),
            ]
        )
        inside = centre @ self._xyz[:, low:high] >= math.cos(math.radians(radius))
        inside &= self.magnitude[low:high] <= magnitude
        index = np.flatnonzero(inside) + low
        truncated = len(index) > limit
        if truncated:
            index = index[np.argpartition(self.magnitude[index], limit - 1)[:limit]]
        index = index[np.argsort(self.magnitude[index], kind="stable")]
        return StarField(self.ra[index], self.dec[index], self.magnitude[index], truncated)


_lock = threading.Lock()
_bundled: StarCatalog | None = None


def bundled_stars() -> StarCatalog:
    """The bundled stars, loaded on first use (blocking: call it from a thread); none if
    the file was left out (its licence forbids commercial use, ADR 0020)."""
    global _bundled
    with _lock:
        if _bundled is None:
            try:
                _bundled = StarCatalog.load()
            except FileNotFoundError:
                _bundled = StarCatalog.from_stars([])
        return _bundled


def loaded_stars() -> StarCatalog | None:
    return _bundled
