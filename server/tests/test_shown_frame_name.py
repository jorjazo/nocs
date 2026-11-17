"""The name of a frame saved from Explore's screen, from its plate solution (ADR 0054)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from nocs.devices import FrameType
from nocs.imaging.capture import Shot, solved_name
from nocs.state import Json

ARRIVED = datetime(2026, 11, 17, 3, 0, 30, tzinfo=UTC)
SHOT = Shot(Path("frame.fits"), 1, FrameType.LIGHT, ARRIVED, 30.0, None)


def solution(taken: str = "2026-11-17T03:00:15+00:00") -> dict[str, Json]:
    return {"taken": taken, "ra": 5.5881, "dec": -5.3911, "fov": [1.2, 0.8]}


def test_named_by_the_object_at_its_centre() -> None:
    asked: list[tuple[float, float, float]] = []

    def namer(ra: float, dec: float, radius: float) -> str | None:
        asked.append((ra, dec, radius))
        return "M 42"

    assert solved_name(solution(), SHOT, namer) == "M 42"
    assert asked == [(5.5881, -5.3911, 0.4)]


def test_not_by_the_solution_of_another_frame() -> None:
    def namer(ra: float, dec: float, radius: float) -> str | None:
        raise AssertionError("not asked")

    other = solution("2026-11-17T02:59:45+00:00")
    assert solved_name(other, SHOT, namer) is None
    assert solved_name(None, SHOT, namer) is None
    assert solved_name({"taken": "x"}, SHOT, namer) is None
