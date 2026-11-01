"""The flats wizard with a fake camera on a panel and under a twilight sky (ADR 0036)."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
from nocs.calibration.twilight import flat_spot, sun, windows
from nocs.devices import Coordinates, FrameType, Location
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


SITE = Location(-30.0277, -70.6733, 700)
EVENING = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)


class FakeMount:
    def __init__(self) -> None:
        self.slews: list[tuple[float, float]] = []
        self.tracking: list[bool | None] = []

    async def slew(
        self, context: JobContext, ra: float, dec: float, *, force: bool = False
    ) -> Coordinates:
        self.slews.append((ra, dec))
        return Coordinates(ra, dec)

    async def set_tracking(
        self, on: bool | None, mode: str | None = None, *, job: str | None = None
    ) -> None:
        self.tracking.append(on)


async def sky_run(
    camera: FakeCamera, plan: FlatPlan, start: datetime
) -> tuple[dict[str, Any], dict[str, Any], FakeMount]:
    store = StateStore()
    jobs = JobManager(store)
    mount = FakeMount()

    async def sleep(seconds: float) -> None:
        camera.now += seconds

    service = FlatsService(
        store,
        jobs,
        camera,
        lambda: camera,
        lambda: None,
        Levels(),
        clock=lambda: camera.now,
        site=lambda: SITE,
        mount=lambda: mount,
        now=lambda: start + timedelta(seconds=camera.now),
        sleep=sleep,
    )
    job_id = service.start(plan)
    await jobs.wait(job_id)
    state = store.get(("flats",))
    assert isinstance(state, dict)
    FlatsState.model_validate(state)
    job = store.get(("jobs", job_id))
    assert isinstance(job, dict)
    return job, state, mount


def test_twilight_windows_at_the_lab_site() -> None:
    found = windows(SITE, EVENING)
    assert [w.phase for w in found] == ["dusk", "dawn"]
    for window in found:
        assert 25 * 60 < (window.end - window.start).total_seconds() < 70 * 60
    dusk = found[0]
    assert sun(SITE, dusk.start)[0] == pytest.approx(-1, abs=0.3)
    spot = flat_spot(SITE, dusk.start)
    assert -90 <= spot.dec <= 90


async def test_dusk_flats_wait_follow_the_sky_and_put_narrowband_first(tmp_path: Path) -> None:
    dusk = windows(SITE, EVENING)[0]
    # 5 minutes before the window; the sky halves every 2 minutes.
    start = dusk.start - timedelta(minutes=5)
    rates = {"L": 3e6, "Ha": 3e6 / 60}

    def light(filter: str | None, now: float) -> float:
        return rates[filter or "L"] * 0.5 ** (now / 120)

    camera = FakeCamera(tmp_path, light)
    plan = FlatPlan(
        source="sky",
        filters=[FlatFilter(filter="L", count=6), FlatFilter(filter="Ha", count=4)],
        min_exposure=0.1,
        max_exposure=30,
    )
    job, state, mount = await sky_run(camera, plan, start)
    assert job["state"] == "succeeded", (job, state)
    assert [f["filter"] for f in state["filters"]] == ["Ha", "L"]
    assert [(f["done"], f["state"]) for f in state["filters"]] == [(4, "done"), (6, "done")]
    assert [f for f, _, _ in camera.kept] == ["Ha"] * 4 + ["L"] * 6
    target = 0.5 * FULL_SCALE
    assert all(abs(level - target) <= 0.2 * FULL_SCALE for _, _, level in camera.kept)
    exposures = [e for f, e, _ in camera.kept if f == "L"]
    assert exposures == sorted(exposures)  # longer as it gets darker
    assert len(mount.slews) == 1
    assert mount.tracking == [False]
    assert camera.now > 5 * 60  # it waited for the window


async def test_sky_flats_after_the_twilight_fail(tmp_path: Path) -> None:
    dusk = windows(SITE, EVENING)[0]
    camera = FakeCamera(tmp_path, lambda f, _: 1.0)
    plan = FlatPlan(source="sky", filters=[FlatFilter(filter="L")])
    job, state, mount = await sky_run(camera, plan, dusk.end + timedelta(minutes=20))
    assert job["state"] == "failed"
    assert "twilight is over" in (state["error"] or "")
    assert not mount.slews
