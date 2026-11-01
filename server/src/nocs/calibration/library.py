"""Which calibration frames match which lights, and what is missing (ADR 0036).

Lights are grouped by what their darks must share (camera, frame size, binning,
gain, offset, exposure, temperature) and their filter. Each group then counts the
darks, flats and bias in the catalog that match it, from any night within an age,
and what is missing for the wanted counts. Flats need their own bias (or darks of
their exposure), reported with them.

Pure functions over catalog rows: the caller reads the catalog in a thread.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from nocs.storage import FrameRow

DARK_TEMPERATURE = 2.0
"""°C a dark may differ from its lights."""
BIAS_TEMPERATURE = 5.0
EXPOSURE_TOLERANCE = 0.01
"""Fraction an exposure may differ and still be the same."""
DARK_DAYS = 180
FLAT_DAYS = 30
FLAT_ROTATION = 1.0
"""Degrees, modulo 180 (a meridian flip turns the image, not the camera)."""


@dataclass(frozen=True, slots=True)
class Wanted:
    darks: int = 20
    bias: int = 50
    flats: int = 20


@dataclass(frozen=True, slots=True)
class Setup:
    """What every calibration frame shares with its lights, but flats' gain and offset."""

    camera: str
    width: int | None
    height: int | None
    binning: int | None
    gain: float | None
    offset: float | None


@dataclass(frozen=True, slots=True)
class Light:
    """Lights saved, or planned for a sequence (no night yet, ``count`` planned)."""

    setup: Setup
    filter: str | None
    exposure: float
    temperature: float | None
    night: date
    count: int = 1
    rotation: float | None = None


@dataclass(slots=True)
class Match:
    frames: list[int] = field(default_factory=list[int])
    nights: set[str] = field(default_factory=set[str])
    temperatures: list[float] = field(default_factory=list[float])

    def add(self, row: FrameRow) -> None:
        self.frames.append(row.id)
        self.nights.add(row.night)
        if row.temperature is not None:
            self.temperatures.append(row.temperature)

    @property
    def temperature(self) -> float | None:
        return round(statistics.median(self.temperatures), 1) if self.temperatures else None


@dataclass(frozen=True, slots=True)
class Need:
    """Frames to take: what the darks sequence and the flats wizard are built from."""

    kind: Literal["dark", "bias", "flat"]
    setup: Setup
    count: int
    exposure: float | None = None
    temperature: float | None = None
    filter: str | None = None


@dataclass(slots=True)
class Group:
    setup: Setup
    filter: str | None
    exposure: float
    temperature: float | None
    lights: int
    nights: set[date]
    darks: Match = field(default_factory=Match)
    flats: Match = field(default_factory=Match)
    bias: Match = field(default_factory=Match)
    """The bias of the lights' setup: darks need none, but flats taken at it do."""
    flat_calibration: Match = field(default_factory=Match)
    """Bias or darks for the matched flats."""


@dataclass(frozen=True, slots=True)
class Report:
    groups: list[Group]
    needs: list[Need]

    @property
    def frames(self) -> list[int]:
        """Every matched calibration frame, without repeats."""
        found: set[int] = set()
        for group in self.groups:
            for match in (group.darks, group.flats, group.flat_calibration):
                found.update(match.frames)
        return sorted(found)


def setup_of(row: FrameRow) -> Setup:
    return Setup(row.camera, row.width, row.height, row.binning, row.gain, row.offset)


def lights_of(rows: Iterable[FrameRow]) -> list[Light]:
    return [
        Light(
            setup_of(row),
            row.filter,
            row.exposure,
            row.temperature,
            date.fromisoformat(row.night),
            rotation=row.rotation,
        )
        for row in rows
        if row.frame_type == "light"
    ]


def report(lights: list[Light], calibration: list[FrameRow], wanted: Wanted) -> Report:
    groups = _groups(lights)
    for group in groups:
        _match(group, calibration, lights)
    return Report(groups, _needs(groups, wanted))


def _same_exposure(a: float, b: float) -> bool:
    return abs(a - b) <= EXPOSURE_TOLERANCE * max(a, b)


def _near(a: float | None, b: float | None, tolerance: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tolerance


def _days(row: FrameRow, nights: set[date]) -> int:
    night = date.fromisoformat(row.night)
    return min(abs((night - n).days) for n in nights)


def _rotation_matches(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    difference = abs(a - b) % 180
    return min(difference, 180 - difference) <= FLAT_ROTATION


def _groups(lights: list[Light]) -> list[Group]:
    """Lights by setup, filter and exposure, then by temperatures within the dark tolerance."""
    by_key: dict[tuple[Setup, str | None, float], list[Light]] = {}
    for light in lights:
        key = next(
            (
                k
                for k in by_key
                if k[0] == light.setup
                and k[1] == light.filter
                and _same_exposure(k[2], light.exposure)
            ),
            (light.setup, light.filter, light.exposure),
        )
        by_key.setdefault(key, []).append(light)
    groups: list[Group] = []
    for (setup, filter, exposure), members in by_key.items():
        unknown = [m for m in members if m.temperature is None]
        known = sorted((m for m in members if m.temperature is not None), key=_temperature)
        clusters: list[list[Light]] = [unknown] if unknown else []
        for light in known:
            if clusters and clusters[-1] and clusters[-1][0].temperature is not None:
                first = _temperature(clusters[-1][0])
                if _temperature(light) - first <= 2 * DARK_TEMPERATURE:
                    clusters[-1].append(light)
                    continue
            clusters.append([light])
        for cluster in clusters:
            temperatures = [_temperature(m) for m in cluster if m.temperature is not None]
            groups.append(
                Group(
                    setup,
                    filter,
                    exposure,
                    round(statistics.median(temperatures), 1) if temperatures else None,
                    sum(m.count for m in cluster),
                    {m.night for m in cluster},
                )
            )
    groups.sort(key=lambda g: (g.setup.camera, g.filter or "", g.exposure, g.temperature or 0))
    return groups


def _temperature(light: Light) -> float:
    assert light.temperature is not None
    return light.temperature


def _match(group: Group, calibration: list[FrameRow], lights: list[Light]) -> None:
    setup = group.setup
    rotations = {
        light.rotation
        for light in lights
        if light.setup == setup and light.filter == group.filter and light.rotation is not None
    }
    flats: list[FrameRow] = []
    for row in calibration:
        if row.frame_type == "flat":
            same_train = (
                row.camera == setup.camera
                and (row.width, row.height, row.binning)
                == (setup.width, setup.height, setup.binning)
                and row.filter == group.filter
            )
            if not same_train:
                continue
            night = date.fromisoformat(row.night)
            if night in group.nights or (
                _days(row, group.nights) <= FLAT_DAYS
                and any(_rotation_matches(row.rotation, r) for r in rotations)
            ):
                group.flats.add(row)
                flats.append(row)
            continue
        if setup_of(row) != setup or _days(row, group.nights) > DARK_DAYS:
            continue
        if row.frame_type == "dark":
            if _same_exposure(row.exposure, group.exposure) and _near(
                row.temperature, group.temperature, DARK_TEMPERATURE
            ):
                group.darks.add(row)
        elif row.frame_type == "bias" and _near(
            row.temperature, group.temperature, BIAS_TEMPERATURE
        ):
            group.bias.add(row)
    _match_flat_calibration(group, flats, calibration)


def _match_flat_calibration(
    group: Group, flats: list[FrameRow], calibration: list[FrameRow]
) -> None:
    """Bias for the flats' setup; else darks for every exposure the flats used."""
    if not flats:
        return
    nights = {date.fromisoformat(f.night) for f in flats}
    temperature = _median([f.temperature for f in flats])
    setup = setup_of(flats[0])
    candidates = [
        row
        for row in calibration
        if row.frame_type in ("bias", "dark")
        and setup_of(row) == setup
        and _days(row, nights) <= DARK_DAYS
    ]
    bias = [
        row
        for row in candidates
        if row.frame_type == "bias" and _near(row.temperature, temperature, BIAS_TEMPERATURE)
    ]
    if bias:
        for row in bias:
            group.flat_calibration.add(row)
        return
    darks = [
        row
        for row in candidates
        if row.frame_type == "dark" and _near(row.temperature, temperature, DARK_TEMPERATURE)
    ]
    exposures = {f.exposure for f in flats}
    if all(any(_same_exposure(d.exposure, e) for d in darks) for e in exposures):
        for row in darks:
            if any(_same_exposure(row.exposure, e) for e in exposures):
                group.flat_calibration.add(row)


def _median(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return round(statistics.median(known), 1) if known else None


def _needs(groups: list[Group], wanted: Wanted) -> list[Need]:
    """What to take, merged across groups: one set of darks serves every filter."""
    darks: dict[tuple[Setup, float, float | None], int] = {}
    bias: dict[tuple[Setup, float | None], int] = {}
    flats: dict[tuple[Setup, str | None], int] = {}
    for group in groups:
        setup = group.setup
        dark_key = next(
            (
                k
                for k in darks
                if k[0] == setup
                and _same_exposure(k[1], group.exposure)
                and _near(k[2], group.temperature, DARK_TEMPERATURE)
            ),
            (setup, group.exposure, group.temperature),
        )
        missing = max(0, wanted.darks - len(group.darks.frames))
        darks[dark_key] = min(darks.get(dark_key, missing), missing)
        missing = max(0, wanted.flats - len(group.flats.frames))
        flat_key = (setup, group.filter)
        flats[flat_key] = min(flats.get(flat_key, missing), missing)
        # Flats will be taken at the lights' setup: their bias is the lights' bias.
        if missing or not group.flat_calibration.frames:
            bias_key = next(
                (
                    k
                    for k in bias
                    if k[0] == setup and _near(k[1], group.temperature, BIAS_TEMPERATURE)
                ),
                (setup, group.temperature),
            )
            missing = max(0, wanted.bias - len(group.bias.frames))
            bias[bias_key] = min(bias.get(bias_key, missing), missing)
    needs = [
        Need("bias", setup, count, temperature=temperature)
        for (setup, temperature), count in bias.items()
        if count
    ]
    needs += [
        Need("dark", setup, count, exposure=exposure, temperature=temperature)
        for (setup, exposure, temperature), count in sorted(
            darks.items(), key=lambda item: item[0][1]
        )
        if count
    ]
    needs += [
        Need("flat", setup, count, filter=filter)
        for (setup, filter), count in flats.items()
        if count
    ]
    return needs
