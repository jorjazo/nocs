"""Planning a focus sweep and judging its points (ADR 0021).

A sweep takes frames at evenly spaced focuser positions around a starting one
and measures their HFR. Every position is reached moving the same way (the
approach direction), so backlash in the focuser's gears is always taken up
the same way: a move against that direction goes past its target by an
overshoot and comes back.

``assess`` decides, from the points so far, whether to fit the curve, to add
points on one side because the curve has not turned yet, or to give up.
"""

from __future__ import annotations

import itertools
from collections.abc import Container, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from nocs.focus.curve import Fit, FitError, fit_hyperbola


class Direction(IntEnum):
    """Which way the focuser moves: towards higher positions (outward) or lower ones."""

    OUTWARD = 1
    INWARD = -1


class Problem(StrEnum):
    NO_STARS = "no_stars"
    """Too few stars at the starting position: clouds, the cap, far out of focus."""
    TOO_FEW_STARS = "too_few_stars"
    """Too many points of the sweep without enough stars."""
    NOT_TURNING = "not_turning"
    """The HFR keeps falling towards one end: focus lies beyond the sweep."""
    FLAT = "flat"
    """The HFR hardly changes across the sweep: no real stars (hot pixels with the cap
    on, as in the lab), or a step too small to leave focus."""
    BAD_FIT = "bad_fit"
    """The points do not follow a V closely enough."""
    WORSE = "worse"
    """The frame at the fitted focus is worse than where the run started."""
    BACKLASH = "backlash"
    """The first points of the sweep show the same HFR although the focuser moved: the
    overshoot does not take up the focuser's backlash."""


@dataclass(frozen=True, slots=True)
class Point:
    position: int
    hfr: float | None
    """Median HFR in unbinned pixels; ``None`` without stars."""
    stars: int


@dataclass(frozen=True, slots=True)
class Criteria:
    min_stars: int = 10
    """Stars a frame needs for its HFR to count."""
    min_points: int = 5
    """Points with enough stars needed for a fit."""
    min_side_points: int = 2
    """Points needed on each side of the lowest one before the curve has turned."""
    min_r_squared: float = 0.8
    min_contrast: float = 1.2
    """How many times the smallest HFR the largest one must be for a sweep to show a V."""
    plateau_points: int = 3
    """Points at the start of a sweep with the same HFR that mean backlash."""
    plateau_tolerance: float = 0.08
    """How far (a fraction) their HFRs may differ and still count as the same."""


DEFAULT_CRITERIA = Criteria()
PLATEAU_CONTRAST = 0.25
"""A plateau changes per step less than this fraction of what the points after it do."""


@dataclass(frozen=True, slots=True)
class Verdict:
    fit: Fit | None = None
    """The curve, when the points make a good one."""
    extend: Direction | None = None
    """Add points beyond the end this way (the curve has not turned there yet)."""
    problem: Problem | None = None
    detail: str | None = None
    """What went wrong, for logs and job errors."""
    overshoot: int | None = None
    """For backlash: an overshoot that would take it up."""


def sweep_positions(
    centre: int, step: int, count: int, direction: Direction, maximum: int | None
) -> list[int]:
    """``count`` positions ``step`` apart around ``centre``, in the order they are taken.

    The sweep is shifted, not cut short, when it would pass the focuser's travel
    (0 to ``maximum``).
    """
    if step <= 0:
        raise ValueError("the step must be positive")
    if count < 3:
        raise ValueError("a sweep needs at least three points")
    width = step * (count - 1)
    if maximum is not None and width > maximum:
        raise ValueError(f"{count} points {step} steps apart do not fit in 0..{maximum}")
    low = centre - width // 2
    if maximum is not None:
        low = min(low, maximum - width)
    low = max(low, 0)
    positions = [low + i * step for i in range(count)]
    return positions if direction is Direction.OUTWARD else positions[::-1]


def extension(
    positions: Sequence[int], towards: Direction, step: int, count: int, maximum: int | None
) -> list[int]:
    """Up to ``count`` more positions beyond the end of the sweep ``towards`` one side.

    Fewer (or none) when the focuser's travel ends first. Returned in the order
    they are taken, nearest first.
    """
    edge = max(positions) if towards is Direction.OUTWARD else min(positions)
    added: list[int] = []
    for i in range(1, count + 1):
        position = edge + towards * i * step
        if position < 0 or (maximum is not None and position > maximum):
            break
        added.append(position)
    return added


def approach(
    current: int, target: int, direction: Direction, overshoot: int, maximum: int | None
) -> list[int]:
    """The moves that reach ``target`` travelling ``direction`` at the end.

    A move the other way goes ``overshoot`` steps past the target first, within
    the focuser's travel.
    """
    if overshoot <= 0 or target == current or (target - current) * direction > 0:
        return [target]
    beyond = target - direction * overshoot
    beyond = max(beyond, 0)
    if maximum is not None:
        beyond = min(beyond, maximum)
    return [target] if beyond == target else [beyond, target]


def assess(
    points: Sequence[Point],
    criteria: Criteria = DEFAULT_CRITERIA,
    *,
    can_extend: Container[Direction] = (),
) -> Verdict:
    """Judge a sweep: fit it, extend it on one side, or give up.

    ``can_extend`` holds the sides on which points may still be added (the
    focuser's travel and the run's budget allow it).
    """
    usable = sorted(
        (p for p in points if p.hfr is not None and p.stars >= criteria.min_stars),
        key=lambda p: p.position,
    )
    if len(usable) < criteria.min_points:
        return Verdict(
            problem=Problem.TOO_FEW_STARS,
            detail=(
                f"only {len(usable)} of {len(points)} points had {criteria.min_stars} stars"
                f" or more ({criteria.min_points} needed)"
            ),
        )
    hfrs = [p.hfr for p in usable if p.hfr is not None]
    if max(hfrs) >= min(hfrs) * criteria.min_contrast and (found := plateau(points, criteria)):
        count, span, overshoot = found
        return Verdict(
            problem=Problem.BACKLASH,
            detail=(
                f"the first {count} points ({span} steps) show the same HFR: the focuser's"
                f" backlash is not taken up; try an overshoot of {overshoot}"
            ),
            overshoot=overshoot,
        )
    if max(hfrs) < min(hfrs) * criteria.min_contrast:
        return Verdict(
            problem=Problem.FLAT,
            detail=f"the HFR hardly changes across the sweep ({min(hfrs):.2f} to {max(hfrs):.2f})",
        )
    lowest = hfrs.index(min(hfrs))
    for side, count in ((Direction.INWARD, lowest), (Direction.OUTWARD, len(usable) - 1 - lowest)):
        if count < criteria.min_side_points:
            if side in can_extend:
                return Verdict(extend=side)
            edge = usable[0].position if side is Direction.INWARD else usable[-1].position
            return Verdict(
                problem=Problem.NOT_TURNING,
                detail=f"the HFR is still falling at {edge}: focus lies beyond the sweep",
            )
    try:
        fit = fit_hyperbola([p.position for p in usable], hfrs)
    except FitError as e:
        return Verdict(problem=Problem.BAD_FIT, detail=str(e))
    best = fit.curve.c
    if not usable[0].position <= best <= usable[-1].position:
        return Verdict(
            problem=Problem.BAD_FIT,
            detail=f"the fitted focus {best:.0f} lies outside the sweep",
        )
    if fit.r_squared < criteria.min_r_squared:
        return Verdict(
            problem=Problem.BAD_FIT,
            detail=f"the points follow the curve poorly (R² {fit.r_squared:.2f})",
        )
    return Verdict(fit=fit)


def plateau(
    points: Sequence[Point], criteria: Criteria = DEFAULT_CRITERIA
) -> tuple[int, int, int] | None:
    """Backlash at the start of a sweep: (points, steps they span, an overshoot to try).

    The first points, in the order taken, keep the same HFR while the focuser's
    position changes: its gears were taking up slack, and the optics did not move.
    The overshoot suggested covers that span and one step more, with half again as
    margin.
    """
    usable = [p for p in points if p.hfr is not None and p.stars >= criteria.min_stars]
    if len(usable) <= criteria.plateau_points:
        return None
    first = usable[0].hfr
    assert first is not None
    count = 1
    while count < len(usable):
        hfr = usable[count].hfr
        assert hfr is not None
        if abs(hfr - first) > criteria.plateau_tolerance * first:
            break
        count += 1
    if count < criteria.plateau_points or count > len(usable) - 2:
        return None
    # On the far arm of a V the HFR changes slowly too, but steadily: a plateau changes
    # far less than the points right after it.
    hfrs = [p.hfr for p in usable if p.hfr is not None]
    within = abs(hfrs[count - 1] - hfrs[0]) / (count - 1)
    after = hfrs[count - 1 : count + 3]
    beyond = sum(abs(b - a) for a, b in itertools.pairwise(after)) / (len(after) - 1)
    if within >= PLATEAU_CONTRAST * beyond:
        return None
    span = abs(usable[count - 1].position - usable[0].position)
    step = abs(usable[1].position - usable[0].position)
    return count, span, _round_up(1.5 * (span + step))


def _round_up(value: float) -> int:
    """Up to two significant digits: 1035 → 1100."""
    unit = 10 ** max(0, len(str(int(value))) - 2)
    return int(-(-value // unit) * unit)


def suggest_step(fit: Fit, side_points: int, edge_ratio: float = 2.5) -> int:
    """The step that would put the ends of a sweep at ``edge_ratio`` times the best HFR.

    Ends far enough out of focus make the arms of the V, and with them the fit,
    reliable; ends too far lose their stars.
    """
    if side_points < 1:
        raise ValueError("a sweep has at least one point on each side")
    return max(1, round(fit.curve.distance_for(fit.curve.a * edge_ratio) / side_points))
