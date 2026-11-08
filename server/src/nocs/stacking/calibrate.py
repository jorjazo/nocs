"""Which calibration frames a live stack uses (ADR 0039), from the library (ADR 0036).

The stack's lights form one light group of the library; its matches decide the
masters: darks of the lights' exposure (else their bias) to subtract, and flats of
the filter with their own bias or dark flats. A flat with neither is not used: its
level would include the pedestal and every correction would be off. At most the
newest ``MOST`` frames of each kind go into a master.

A master is named by its kind and the frames it comes from, so the same frames
make the same file, which the worker builds once.

Pure functions over catalog rows: the caller reads the catalog in a thread.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from nocs.calibration.library import Light, Match, Wanted, report
from nocs.stacking.masters import Kind
from nocs.storage import FrameRow

MOST = 20
"""Frames at most in a master."""


@dataclass(frozen=True, slots=True)
class MasterSpec:
    kind: Kind
    frames: tuple[int, ...]
    """Catalog ids, newest first."""

    @property
    def key(self) -> str:
        digest = hashlib.sha256(",".join(map(str, sorted(self.frames))).encode()).hexdigest()
        return f"{self.kind}-{digest[:20]}"


@dataclass(frozen=True, slots=True)
class MasterPlan:
    dark: MasterSpec | None
    """Darks, or bias when there are no darks; None: nothing to subtract."""
    flat: MasterSpec | None
    flat_offset: MasterSpec | None
    """The flats' own bias or dark flats; set whenever ``flat`` is."""
    notes: tuple[str, ...]
    """What is used and what is missing, for the log."""
    flats_unused: bool = False
    """Flats were found, but not their bias or dark flats."""

    @property
    def specs(self) -> list[MasterSpec]:
        """Masters to build, each before any that needs it."""
        return [s for s in (self.dark, self.flat_offset, self.flat) if s is not None]


def plan(light: Light, calibration: list[FrameRow]) -> MasterPlan:
    """The masters for a stack of lights like ``light``."""
    found = report([light], calibration, Wanted())
    rows = {row.id: row for row in calibration}
    notes: list[str] = []
    if not found.groups:
        return MasterPlan(None, None, None, ("no calibration",))
    group = found.groups[0]
    dark: MasterSpec | None = None
    if group.darks.frames:
        dark = _spec("dark", group.darks, rows)
        notes.append(f"darks: {len(dark.frames)}")
    elif group.bias.frames:
        dark = _spec("bias", group.bias, rows)
        notes.append(f"no darks; bias: {len(dark.frames)}")
    else:
        notes.append("no darks or bias")
    flat: MasterSpec | None = None
    offset: MasterSpec | None = None
    if group.flats.frames and group.flat_calibration.frames:
        flat = _spec("flat", group.flats, rows)
        offset_kind: Kind = (
            "bias"
            if all(rows[i].frame_type == "bias" for i in group.flat_calibration.frames)
            else "dark"
        )
        offset = _spec(offset_kind, group.flat_calibration, rows)
        notes.append(f"flats: {len(flat.frames)}")
    elif group.flats.frames:
        notes.append("flats without their bias or dark flats: not used")
    else:
        notes.append("no flats")
    unused = bool(group.flats.frames) and flat is None
    return MasterPlan(dark, flat, offset, tuple(notes), unused)


def _spec(kind: Kind, match: Match, rows: dict[int, FrameRow]) -> MasterSpec:
    newest = sorted(match.frames, key=lambda i: (rows[i].started, i), reverse=True)
    return MasterSpec(kind, tuple(newest[:MOST]))
