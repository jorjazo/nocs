"""The flats wizard with a fake camera on a panel and under a twilight sky (ADR 0036)."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nocs.api.schemas import FlatsState
from nocs.calibration.flats import (
    FULL_SCALE,
    FlatFilter,
    FlatPlan,
    FlatsService,
    Sample,
    next_exposure,
    trend_of,
)
from nocs.devices import FrameType
from nocs.equipment import Role
from nocs.imaging import CameraSettings, Shot
from nocs.imaging.capture import Captured
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, StateStore

PEDESTAL = 800.0


class FakeCamera:
    """Light in ADU per second by filter, ``light(filter, now)``; clipped at full scale."""

    def __init__(self, tmp: Path, light: Callable[[str | None, float], float]) -> None:
        self.tmp = tmp
        self.light = light
        self.now = 0.0
        self.filter: str | None = None
        self.levels: dict[str, float] = {}
        self.kept: list[tuple[str | None, float, float]] = []
        self.taken = 0
        self.ids = itertools.count(1)
        self.settings: list[CameraSettings] = []

    def camera(self, role: Role) -> object:
        return self

    async def configure(
        self, role: Role, settings: CameraSettings, *, job: str | None = None
    ) -> None:
        self.settings.append(settings)

    async def take(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        label: str = "",
    ) -> Shot:
        self.taken += 1
        middle = self.now + seconds / 2
        signal = 0.0 if frame_type is FrameType.BIAS else self.light(self.filter, middle) * seconds
        self.now += seconds + 2
        path = self.tmp / f"{self.taken}.fits"
        path.write_bytes(b"")
        self.levels[path.name] = min(PEDESTAL + signal, FULL_SCALE)
        return Shot(path, 0, frame_type or FrameType.LIGHT, datetime.now(UTC), seconds, "RGGB")

    async def level(self, shot: Shot) -> float:
        return self.levels[shot.path.name]

    async def keep(self, context: JobContext, role: Role, shot: Shot, label: str = "") -> Captured:
        self.kept.append((self.filter, shot.exposure, self.levels[shot.path.name]))
        shot.path.unlink()  # storage moves it
        return Captured({"id": next(self.ids)}, None, None)

    async def select_in(self, context: JobContext, filter: int | str) -> Json:
        self.filter = str(filter)
        return {"filter": self.filter}


class Levels:
    def __init__(self) -> None:
        self.levels: dict[int, float | None] = {}

    def set_level(self, frame_id: int, level: float | None) -> None:
        self.levels[frame_id] = level


async def run(camera: FakeCamera, plan: FlatPlan) -> tuple[dict[str, Any], dict[str, Any]]:
    store = StateStore()
    jobs = JobManager(store)
    levels = Levels()
    service = FlatsService(
        store, jobs, camera, lambda: camera, lambda: None, levels, clock=lambda: camera.now
    )
    job_id = service.start(plan)
    await jobs.wait(job_id)
    state = store.get(("flats",))
    assert isinstance(state, dict)
    FlatsState.model_validate(state)
    job = store.get(("jobs", job_id))
    assert isinstance(job, dict)
    assert all(level is not None for level in levels.levels.values())
    return job, state


def leftovers(directory: Path) -> list[Path]:
    return list(directory.iterdir())


def test_next_exposure_scales_above_the_pedestal() -> None:
    sample = Sample(1.0, PEDESTAL + 10000, 0)
    assert next_exposure(sample, PEDESTAL, PEDESTAL + 30000) == pytest.approx(3.0)
    assert next_exposure(Sample(1.0, FULL_SCALE, 0), PEDESTAL, 30000) == 0.1
    assert next_exposure(Sample(1.0, PEDESTAL + 100, 0), PEDESTAL, 30000) == 10
    # Getting darker by half every 10 s, 10 s ahead: twice as long.
    trend = 0.5 ** (1 / 10)
    longer = next_exposure(sample, PEDESTAL, PEDESTAL + 30000, trend=trend, ahead=10)
    assert longer == pytest.approx(6.0)
    samples = [Sample(1, PEDESTAL + 20000, 0), Sample(1, PEDESTAL + 10000, 10)]
    assert trend_of(samples, PEDESTAL) == pytest.approx(trend)


async def test_panel_flats_find_each_filters_exposure(tmp_path: Path) -> None:
    rates = {"L": 40000.0, "Ha": 600.0}
    camera = FakeCamera(tmp_path, lambda f, _: rates[f or "L"])
    plan = FlatPlan(
        filters=[FlatFilter(filter="L", count=5), FlatFilter(filter="Ha", count=3)], gain=100
    )
    job, state = await run(camera, plan)
    assert job["state"] == "succeeded", job
    assert [(f["filter"], f["done"], f["state"]) for f in state["filters"]] == [
        ("L", 5, "done"),
        ("Ha", 3, "done"),
    ]
    target = 0.5 * FULL_SCALE
    assert all(abs(level - target) <= 0.1 * FULL_SCALE for _, _, level in camera.kept)
    assert {f: round(e, 2) for f, e, _ in camera.kept} == {"L": 0.8, "Ha": 53.28}
    assert camera.taken < 5 + 3 + 1 + 6  # a few tries, then every frame kept
    assert camera.settings == [CameraSettings(gain=100)]
    assert not leftovers(tmp_path)  # tries are deleted, kept frames moved by storage


async def test_a_panel_too_bright_says_so(tmp_path: Path) -> None:
    camera = FakeCamera(tmp_path, lambda f, _: 1e8)
    job, state = await run(camera, FlatPlan(filters=[FlatFilter(filter="L", count=2)]))
    assert job["state"] == "failed"
    [filter] = state["filters"]
    assert filter["state"] == "failed"
    assert "too bright at 0.01 s" in filter["message"]
    assert "too bright" in state["error"]
