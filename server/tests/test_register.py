"""Registration by star triangles on synthetic fields with known transforms."""

import numpy as np
import pytest
from synthstars import Sky, invert, render, sky

from nocs.stacking.register import (
    RegistrationError,
    Stars,
    Transform,
    find_stars,
    register,
)

WIDTH, HEIGHT = 1200, 800


def error(found: Transform, true: Transform) -> float:
    """Largest distance, in pixels, between where the two put the frame's corners."""
    corners = np.array([[0.0, 0.0], [WIDTH, 0.0], [0.0, HEIGHT], [WIDTH, HEIGHT]])
    return float(np.max(np.hypot(*(found.apply(corners) - true.apply(corners)).T)))


def seen(field: Sky, transform: Transform, *, jitter: float = 0.03, seed: int = 3) -> Stars:
    """The stars a frame that ``transform`` takes onto the reference would find in it,
    brightest first, inside the frame."""
    rng = np.random.default_rng(seed)
    where = invert(transform).apply(np.column_stack((field.x, field.y)))
    where += rng.normal(0, jitter, where.shape)
    inside = (
        (where[:, 0] > 8)
        & (where[:, 0] < WIDTH - 8)
        & (where[:, 1] > 8)
        & (where[:, 1] < HEIGHT - 8)
    )
    order = np.argsort(-field.flux[inside])[:50]
    return Stars(where[inside][order, 0], where[inside][order, 1], field.flux[inside][order])


FIELD = sky(400, WIDTH, HEIGHT)
REFERENCE = seen(FIELD, Transform.identity(), seed=4)


@pytest.mark.parametrize(
    ("rotation", "shift"),
    [
        (0.0, (0.0, 0.0)),
        (0.0, (12.3, -7.8)),
        (0.4, (3.0, 2.0)),
        (-2.5, (-40.0, 25.0)),
        (30.0, (100.0, -350.0)),
        (180.0, (1200.0, 800.0)),
        (179.2, (1195.0, 812.0)),
        (-90.0, (200.0, 1000.0)),
    ],
)
def test_recovers_the_transform(rotation: float, shift: tuple[float, float]) -> None:
    true = Transform.of(rotation, shift)
    frame = seen(FIELD, true)
    result = register(frame, REFERENCE)
    assert error(result.transform, true) < 0.05
    assert abs((result.transform.rotation - rotation + 180) % 360 - 180) < 0.01
    assert result.stars >= 15
    assert result.rms < 0.2


def test_false_and_missing_stars() -> None:
    true = Transform.of(1.5, (20.0, -11.0))
    frame = seen(FIELD, true)
    rng = np.random.default_rng(9)
    keep = rng.uniform(size=len(frame)) > 0.3  # 30 % of the stars missing
    false = 5  # and 10 % of the list stars that are not in the reference
    stars = Stars(
        np.concatenate((frame.x[keep], rng.uniform(10, WIDTH - 10, false))),
        np.concatenate((frame.y[keep], rng.uniform(10, HEIGHT - 10, false))),
        np.concatenate((frame.flux[keep], np.full(false, 1e4))),
    )
    assert error(register(stars, REFERENCE).transform, true) < 0.05


def test_a_mirrored_frame_is_refused() -> None:
    frame = seen(FIELD, Transform.of(3.0, (10.0, 5.0)))
    mirrored = Stars(WIDTH - frame.x, frame.y, frame.flux)
    with pytest.raises(RegistrationError, match="mirror"):
        register(mirrored, REFERENCE)


def test_too_few_stars() -> None:
    few = Stars(REFERENCE.x[:4], REFERENCE.y[:4], REFERENCE.flux[:4])
    with pytest.raises(RegistrationError, match="too few stars"):
        register(few, REFERENCE)


def test_another_field_does_not_register() -> None:
    other = seen(sky(400, WIDTH, HEIGHT, seed=77), Transform.identity())
    with pytest.raises(RegistrationError, match="in common"):
        register(other, REFERENCE)


def test_a_different_scale_is_refused() -> None:
    frame = seen(FIELD, Transform.of(0.0, (0.0, 0.0), scale=1.02))
    with pytest.raises(RegistrationError, match="scale"):
        register(frame, REFERENCE)


@pytest.mark.parametrize(
    ("rotation", "shift"),
    [(0.0, (5.4, -3.3)), (0.7, (-18.0, 9.0)), (180.0, (1203.0, 795.0))],
)
def test_on_rendered_frames(rotation: float, shift: tuple[float, float]) -> None:
    true = Transform.of(rotation, shift)
    reference = find_stars(render(FIELD, WIDTH, HEIGHT, seed=10).astype(np.float32))
    frame = find_stars(render(FIELD, WIDTH, HEIGHT, true, seed=11).astype(np.float32))
    assert len(reference) == 50
    result = register(frame, reference)
    assert error(result.transform, true) < 0.1
    assert abs((result.transform.rotation - rotation + 180) % 360 - 180) < 0.01


def test_find_stars_brightest_first_and_away_from_edges() -> None:
    stars = find_stars(render(FIELD, WIDTH, HEIGHT).astype(np.float32), most=30)
    assert len(stars) == 30
    assert np.all(np.diff(stars.flux) <= 0)
    assert stars.x.min() >= 8
    assert stars.x.max() < WIDTH - 8
    assert stars.y.min() >= 8
    assert stars.y.max() < HEIGHT - 8


def test_find_stars_on_an_empty_frame() -> None:
    empty = np.random.default_rng(1).normal(800, 5, (200, 300)).astype(np.float32)
    assert len(find_stars(empty)) == 0
