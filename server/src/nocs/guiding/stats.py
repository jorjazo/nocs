"""Guide steps from PHD2's events, kept for the graph, and their RMS.

Each guiding run (from PHD2's ``StartGuiding``) starts a new history. Its entries are:

- ``step``: a guide frame: where the star was from the lock position (raw RA and
  Dec distances, pixels) and the corrections sent (pulses in ms, positive towards
  west and north);
- ``lost``: a frame without the star;
- ``dither``: PHD2 moved the lock position (pixels).

Every entry has a number of its own (``seq``), increasing for the life of nocsd, so a
client asks only for what it has not seen. RMS is computed as PHD2's graph shows it:
the standard deviation of the raw distances, which leaves out a constant offset, over
the most recent steps that were not settling.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from nocs.state import Json

HISTORY = 3600
"""Entries kept: an hour or two at the usual exposures."""
RMS_WINDOW = 100
"""Steps the RMS covers, as PHD2's graph by default."""

type EntryKind = Literal["step", "lost", "dither"]


@dataclass(frozen=True, slots=True)
class GuideEntry:
    seq: int
    kind: EntryKind
    time: float
    """PHD2's timestamp, Unix seconds."""
    ra: float | None = None
    """Raw RA distance, pixels (a step); the RA move (a dither)."""
    dec: float | None = None
    ra_pulse: int = 0
    """Milliseconds, positive towards west."""
    dec_pulse: int = 0
    """Milliseconds, positive towards north."""
    snr: float | None = None
    hfd: float | None = None
    """Pixels."""
    mass: float | None = None
    settling: bool = False
    """PHD2 was settling after starting to guide or a dither."""

    def to_json(self) -> dict[str, Json]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "time": self.time,
            "ra": self.ra,
            "dec": self.dec,
            "ra_pulse": self.ra_pulse,
            "dec_pulse": self.dec_pulse,
            "snr": self.snr,
            "hfd": self.hfd,
            "mass": self.mass,
            "settling": self.settling,
        }


@dataclass(frozen=True, slots=True)
class Rms:
    """In pixels."""

    count: int
    ra: float
    dec: float
    peak_ra: float
    peak_dec: float

    @property
    def total(self) -> float:
        return math.hypot(self.ra, self.dec)


def rms(entries: Iterable[GuideEntry]) -> Rms | None:
    """RMS of the guide steps among ``entries``; None without any."""
    steps = [e for e in entries if e.kind == "step" and e.ra is not None and e.dec is not None]
    if not steps:
        return None
    ra = [e.ra for e in steps if e.ra is not None]
    dec = [e.dec for e in steps if e.dec is not None]
    return Rms(len(steps), _deviation(ra), _deviation(dec), max(map(abs, ra)), max(map(abs, dec)))


def _deviation(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _number(data: Mapping[str, Json], key: str) -> float | None:
    value = data.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _pulse(data: Mapping[str, Json], duration: str, direction: str, positive: str) -> int:
    value = _number(data, duration)
    if value is None:
        return 0
    return round(value) if data.get(direction) == positive else -round(value)


class GuideHistory:
    def __init__(self, limit: int = HISTORY) -> None:
        self._entries: deque[GuideEntry] = deque(maxlen=limit)
        self._seq = 0

    def reset(self) -> None:
        """A new guiding run: what came before is not part of its graph."""
        self._entries.clear()

    def add(self, event: str, data: Mapping[str, Json], *, settling: bool) -> GuideEntry | None:
        """Keep what a PHD2 event says about guiding; None for other events."""
        time = _number(data, "Timestamp") or 0.0
        match event:
            case "GuideStep":
                entry = GuideEntry(
                    seq=self._seq + 1,
                    kind="step",
                    time=time,
                    ra=_number(data, "RADistanceRaw"),
                    dec=_number(data, "DECDistanceRaw"),
                    ra_pulse=_pulse(data, "RADuration", "RADirection", "West"),
                    dec_pulse=_pulse(data, "DECDuration", "DECDirection", "North"),
                    snr=_number(data, "SNR"),
                    hfd=_number(data, "HFD"),
                    mass=_number(data, "StarMass"),
                    settling=settling,
                )
            case "StarLost":
                entry = GuideEntry(
                    seq=self._seq + 1,
                    kind="lost",
                    time=time,
                    snr=_number(data, "SNR"),
                    mass=_number(data, "StarMass"),
                    settling=settling,
                )
            case "GuidingDithered":
                entry = GuideEntry(
                    seq=self._seq + 1,
                    kind="dither",
                    time=time,
                    ra=_number(data, "dx"),
                    dec=_number(data, "dy"),
                    settling=settling,
                )
            case _:
                return None
        self._seq = entry.seq
        self._entries.append(entry)
        return entry

    @property
    def last_seq(self) -> int:
        return self._seq

    def after(self, seq: int, limit: int | None = None) -> list[GuideEntry]:
        """Entries numbered above ``seq``, oldest first (the oldest ones if ``limit``)."""
        entries = [e for e in self._entries if e.seq > seq]
        return entries[:limit] if limit is not None else entries

    def between(self, start: float, end: float) -> list[GuideEntry]:
        """Entries with PHD2 timestamps from ``start`` to ``end``."""
        return [e for e in self._entries if start <= e.time <= end]

    def recent_rms(self, window: int = RMS_WINDOW) -> Rms | None:
        """RMS over the last ``window`` steps that were not settling."""
        steps: list[GuideEntry] = []
        for entry in reversed(self._entries):
            if entry.kind == "step" and not entry.settling:
                steps.append(entry)
                if len(steps) == window:
                    break
        return rms(steps)

    def lost_count(self, window: int = RMS_WINDOW) -> int:
        """Frames without the star among the last ``window`` entries."""
        recent = list(self._entries)[-window:]
        return sum(1 for e in recent if e.kind == "lost")
