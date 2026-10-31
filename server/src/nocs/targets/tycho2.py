"""Tycho-2 (ESA, CDS I/259) records to the stars the framing chart bundles (ADR 0020).

Used by ``dev/catalog/build_stars.py``; nocsd only reads the result (``nocs.targets.stars``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from nocs.targets.stars import Star

_SUPPLEMENT_EPOCH = 1991.25


class Tycho2Error(ValueError):
    pass


def johnson_v(bt: float | None, vt: float | None) -> float | None:
    """Approximate Johnson V from Tycho's BT and VT (the catalogue's ReadMe, note 7)."""
    if bt is not None and vt is not None:
        return vt - 0.090 * (bt - vt)
    # Stars with one band only are faint (or Hipparcos stars with Hp in VT).
    return vt if vt is not None else bt


def parse_main(line: str) -> Star:
    """A record of ``tyc2.dat``: the mean J2000 position, or the observed one (~J1991.5)
    for the stars without a mean position (flag X), which have no proper motion."""
    fields = line.split("|")
    if len(fields) < 26:
        raise Tycho2Error(f"short Tycho-2 record: {line!r}")
    if fields[1].strip() == "X":
        ra, dec = _number(fields[24]), _number(fields[25])
    else:
        ra, dec = _number(fields[2]), _number(fields[3])
    return _star(ra, dec, johnson_v(_number(fields[17]), _number(fields[19])), line)


def parse_supplement(line: str) -> Star:
    """A record of ``suppl_1.dat`` (Hipparcos and Tycho-1 stars missing from Tycho-2, the
    brightest among them), at J1991.25: moved to J2000 by its proper motion when it has one."""
    fields = line.split("|")
    if len(fields) < 15:
        raise Tycho2Error(f"short Tycho-2 supplement record: {line!r}")
    ra, dec = _number(fields[2]), _number(fields[3])
    if ra is None or dec is None:
        raise Tycho2Error(f"no position: {line!r}")
    pm_ra, pm_dec = _number(fields[4]), _number(fields[5])
    if pm_ra is not None and pm_dec is not None:
        years = 2000.0 - _SUPPLEMENT_EPOCH
        dec_new = dec + pm_dec * years / 3.6e6
        ra += pm_ra * years / 3.6e6 / max(math.cos(math.radians(dec)), 1e-6)
        dec = dec_new
    # 'H': Hipparcos's Hp stands in VT, and BT is blank.
    return _star(ra % 360, dec, johnson_v(_number(fields[11]), _number(fields[13])), line)


def select(stars: Iterable[Star], magnitude: float) -> list[Star]:
    """The stars down to `magnitude`, in the bundled file's order (declination, then RA)."""
    return sorted((s for s in stars if s.magnitude <= magnitude), key=lambda s: (s.dec, s.ra))


def _star(ra: float | None, dec: float | None, magnitude: float | None, line: str) -> Star:
    if ra is None or dec is None or magnitude is None:
        raise Tycho2Error(f"no position or magnitude: {line!r}")
    return Star(ra=ra / 15, dec=dec, magnitude=magnitude)


def _number(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None
