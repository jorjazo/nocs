"""The V-curve fit and the planning and judging of a focus sweep."""

import math

import numpy as np
import pytest

from nocs.focus.curve import FitError, Hyperbola, fit_hyperbola
from nocs.focus.sweep import (
    Criteria,
    Direction,
    Point,
    Problem,
    approach,
    assess,
    extension,
    suggest_step,
    sweep_positions,
)

# Median HFR (px, sep) of CCD Simulator frames (2 s, 1000 mm, Orion) against the
# Focuser Simulator's position, measured 2026-10-31. Its best focus is 36667: the
# simulator's FWHM is a parabola in the position, so this curve is not a hyperbola.
SIMULATOR = [
    (16667, 5.348),
    (26667, 2.615),
    (31667, 1.884),
    (36667, 1.666),
    (41667, 1.906),
    (46667, 2.492),
    (56667, 5.481),
]


def sweep(curve: Hyperbola, positions: list[int], stars: int = 50) -> list[Point]:
    return [Point(p, curve(p), stars) for p in positions]


# -- fit --------------------------------------------------------------------------


def test_an_exact_hyperbola_is_recovered() -> None:
    truth = Hyperbola(a=2.1, b=900, c=31234)
    positions = [30000 + 300 * i for i in range(9)]
    fit = fit_hyperbola(positions, [truth(p) for p in positions])
    assert fit.curve.a == pytest.approx(2.1, rel=1e-6)
    assert fit.curve.b == pytest.approx(900, rel=1e-6)
    assert fit.curve.c == pytest.approx(31234, abs=0.01)
    assert fit.r_squared == pytest.approx(1)


def test_noise_moves_the_focus_by_a_fraction_of_a_step() -> None:
    truth = Hyperbola(a=2.5, b=400, c=20150)
    positions = [18800 + 300 * i for i in range(9)]
    rng = np.random.default_rng(7)
    for _ in range(20):
        hfrs = [truth(p) * (1 + rng.normal(0, 0.04)) for p in positions]
        fit = fit_hyperbola(positions, hfrs)
        assert abs(fit.curve.c - truth.c) < 300 / 3
        assert fit.r_squared > 0.9


def test_a_sharp_v_fits_too() -> None:
    """Far from focus the arms are straight: a tip of almost nothing still fits."""
    positions = [1000 + 50 * i for i in range(9)]
    hfrs = [0.3 + abs(p - 1210) / 40 for p in positions]
    fit = fit_hyperbola(positions, hfrs)
    assert fit.curve.c == pytest.approx(1210, abs=25)


def test_the_simulator_curve_finds_its_focus() -> None:
    positions, hfrs = zip(*SIMULATOR, strict=True)
    fit = fit_hyperbola(positions, hfrs)
    assert fit.curve.c == pytest.approx(36667, abs=1000)
    assert fit.r_squared > 0.95


def test_points_that_make_no_v_are_refused() -> None:
    positions = [0, 100, 200, 300, 400]
    with pytest.raises(FitError):
        fit_hyperbola(positions, [1.0, 2.0, 3.0, 2.0, 1.0])  # a hump
    with pytest.raises(FitError):
        fit_hyperbola(positions, [2.0, 2.0, 2.0, 2.0, 2.0])
    with pytest.raises(FitError):
        fit_hyperbola(positions[:2], [2.0, 2.0])
    with pytest.raises(FitError):
        fit_hyperbola(positions, [2.0, 1.0, 0.0, 1.0, 2.0])


def test_distance_for_an_hfr() -> None:
    curve = Hyperbola(a=2, b=500, c=1000)
    assert curve.distance_for(2 * math.sqrt(2)) == pytest.approx(500)
    assert curve(1000 + curve.distance_for(5)) == pytest.approx(5)
    assert curve.distance_for(1) == 0


# -- planning ---------------------------------------------------------------------


def test_sweep_positions_around_the_centre() -> None:
    assert sweep_positions(1000, 100, 5, Direction.OUTWARD, 5000) == [800, 900, 1000, 1100, 1200]
    assert sweep_positions(1000, 100, 5, Direction.INWARD, None) == [1200, 1100, 1000, 900, 800]
    # An even count leans to the low side.
    assert sweep_positions(1000, 100, 4, Direction.OUTWARD, None) == [850, 950, 1050, 1150]


def test_a_sweep_is_shifted_to_fit_the_travel() -> None:
    assert sweep_positions(100, 100, 5, Direction.OUTWARD, 5000) == [0, 100, 200, 300, 400]
    assert sweep_positions(4950, 100, 5, Direction.OUTWARD, 5000) == [
        4600,
        4700,
        4800,
        4900,
        5000,
    ]
    with pytest.raises(ValueError, match="do not fit"):
        sweep_positions(500, 300, 5, Direction.OUTWARD, 1000)
    with pytest.raises(ValueError, match="positive"):
        sweep_positions(500, 0, 5, Direction.OUTWARD, 1000)


def test_extension_stops_at_the_end_of_the_travel() -> None:
    positions = [800, 900, 1000]
    assert extension(positions, Direction.OUTWARD, 100, 3, None) == [1100, 1200, 1300]
    assert extension(positions, Direction.INWARD, 300, 4, None) == [500, 200]
    assert extension(positions, Direction.OUTWARD, 100, 3, 1150) == [1100]
    assert extension([0, 100], Direction.INWARD, 100, 3, None) == []


def test_approach_overshoots_only_against_the_direction() -> None:
    assert approach(1000, 1200, Direction.OUTWARD, 150, None) == [1200]
    assert approach(1000, 800, Direction.OUTWARD, 150, None) == [650, 800]
    assert approach(1000, 1200, Direction.INWARD, 150, None) == [1350, 1200]
    assert approach(1000, 800, Direction.INWARD, 150, None) == [800]
    assert approach(1000, 1000, Direction.OUTWARD, 150, None) == [1000]
    assert approach(1000, 800, Direction.OUTWARD, 0, None) == [800]
    # Within the travel: the overshoot is cut at its ends.
    assert approach(1000, 100, Direction.OUTWARD, 150, None) == [0, 100]
    assert approach(1000, 0, Direction.OUTWARD, 150, None) == [0]
    assert approach(1000, 1900, Direction.INWARD, 150, 2000) == [2000, 1900]


# -- judging ----------------------------------------------------------------------

CURVE = Hyperbola(a=2, b=300, c=10000)


def test_a_good_sweep_is_fitted() -> None:
    verdict = assess(sweep(CURVE, [9200 + 200 * i for i in range(9)]))
    assert verdict.problem is None
    assert verdict.extend is None
    assert verdict.fit is not None
    assert verdict.fit.curve.c == pytest.approx(10000, abs=1)


def test_a_curve_that_has_not_turned_is_extended_then_given_up() -> None:
    points = sweep(CURVE, [10400 + 200 * i for i in range(7)])  # all beyond focus
    both = (Direction.INWARD, Direction.OUTWARD)
    assert assess(points, can_extend=both) == assess(points, can_extend=[Direction.INWARD])
    assert assess(points, can_extend=both).extend is Direction.INWARD
    verdict = assess(points, can_extend=[Direction.OUTWARD])
    assert verdict.problem is Problem.NOT_TURNING
    assert verdict.detail is not None
    assert "10400" in verdict.detail

    # One point past the minimum is not enough on that side.
    points = sweep(CURVE, [8600 + 200 * i for i in range(9)])
    assert assess(points, can_extend=both).extend is Direction.OUTWARD


def test_points_without_enough_stars_do_not_count() -> None:
    positions = [9200 + 200 * i for i in range(9)]
    points = [Point(p, CURVE(p), 50 if i % 2 else 3) for i, p in enumerate(positions)]
    verdict = assess(points)
    assert verdict.problem is Problem.TOO_FEW_STARS
    assert verdict.detail == "only 4 of 9 points had 10 stars or more (5 needed)"
    assert assess(points, Criteria(min_stars=3)).fit is not None
    no_hfr = [Point(p.position, None, 50) if p.stars < 10 else p for p in points]
    assert assess(no_hfr).problem is Problem.TOO_FEW_STARS


def test_scattered_points_are_a_bad_fit() -> None:
    positions = [9200 + 200 * i for i in range(9)]
    hfrs = [3.0, 2.2, 3.5, 2.1, 2.0, 3.3, 2.4, 2.2, 3.1]
    verdict = assess([Point(p, h, 50) for p, h in zip(positions, hfrs, strict=True)])
    assert verdict.problem is Problem.BAD_FIT
    assert verdict.fit is None


def test_suggested_step_puts_the_ends_at_the_ratio() -> None:
    fit = fit_hyperbola(*zip(*((p, CURVE(p)) for p in range(9000, 11001, 250)), strict=True))
    step = suggest_step(fit, 4)
    assert CURVE(10000 + 4 * step) == pytest.approx(2.5 * CURVE.a, rel=0.01)


def test_a_flat_sweep_is_not_a_v() -> None:
    """Hot pixels under the cap, as on the lab rig: ~20 "stars" at 0.82-0.84 px everywhere."""
    hfrs = [0.834, 0.832, 0.823, 0.835, 0.824, 0.832, 0.828, 0.83, 0.83]
    points = [Point(4131 + 300 * i, h, 21) for i, h in enumerate(hfrs)]
    verdict = assess(points, can_extend=(Direction.INWARD, Direction.OUTWARD))
    assert verdict.problem is Problem.FLAT
    assert verdict.detail == "the HFR hardly changes across the sweep (0.82 to 0.83)"


def test_a_plateau_at_the_start_of_a_sweep_is_backlash() -> None:
    # The lab EAF on the 380 mm scope (field test, 2026-10-31): ~650 steps of backlash,
    # an overshoot of one 40-step step. The first moves outward only took up slack.
    truth = Hyperbola(a=2.0, b=120, c=10000)
    positions = [9600 + 40 * i for i in range(21)]
    slack = 650
    moved = [max(positions[0], p - slack) for p in positions]
    points = [Point(p, truth(m), 50) for p, m in zip(positions, moved, strict=True)]
    verdict = assess(points)
    assert verdict.problem is Problem.BACKLASH
    assert verdict.overshoot is not None
    assert 1000 <= verdict.overshoot <= 1200
    assert "overshoot of" in (verdict.detail or "")


def test_a_sweep_that_starts_moving_at_once_is_no_plateau() -> None:
    truth = Hyperbola(a=2.0, b=120, c=10000)
    positions = [9600 + 100 * i for i in range(9)]
    assert assess(sweep(truth, positions)).fit is not None
    flat = [Point(p, 2.0, 50) for p in positions]
    assert assess(flat).problem is Problem.FLAT  # no V at all: not backlash
