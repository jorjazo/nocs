"""Temperatures sampled from the state into the catalog (ADR 0021)."""

from datetime import UTC, datetime
from pathlib import Path

from nocs.state import StateStore
from nocs.storage import StorageService
from nocs.storage.environment import EnvironmentLog, sample

NOW = datetime(2026, 10, 31, 2, 0, 30, 123000, tzinfo=UTC)


def test_a_sample_reads_the_focuser_and_the_weather_role() -> None:
    store = StateStore()
    assert sample(store, NOW) is None
    store.set(("focuser",), {"temperature": 8.25})
    taken = sample(store, NOW)
    assert taken is not None
    assert (taken.time, taken.focuser, taken.ambient) == ("2026-10-31T02:00:30+00:00", 8.25, None)
    store.set(("weather",), {"temperature": 11, "humidity": 64.5, "dew_point": 4.6})
    store.set(("focuser",), {"temperature": None})
    taken = sample(store, NOW)
    assert taken is not None
    assert (taken.focuser, taken.ambient, taken.humidity, taken.dew_point) == (None, 11, 64.5, 4.6)


async def test_samples_go_to_the_catalog(tmp_path: Path) -> None:
    store = StateStore()
    storage = StorageService(store, tmp_path / "config", tmp_path / "data", tmp_path / "internal")
    log = EnvironmentLog(store, storage, now=lambda: NOW)
    assert await log.record() is None
    store.set(("weather",), {"temperature": 11.5, "humidity": None, "dew_point": None})
    assert await log.record() is not None
    assert [s.ambient for s in storage.temperatures("2026-10-31")] == [11.5]
    await storage.close()
