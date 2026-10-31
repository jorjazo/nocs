"""Temperatures of the night, sampled into the catalog (ADR 0021).

Once a minute, while the focuser has a probe or a weather role is ready, the
focuser's temperature and the weather role's temperature, humidity and dew
point are read from the state and kept. Autofocus triggers on a temperature
change and the session report read them back.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime

import anyio

from nocs.state import Json, Path, StateStore
from nocs.storage.catalog import TemperatureSample
from nocs.storage.service import StorageService

log = logging.getLogger(__name__)

SAMPLE_SECONDS = 60.0


def number(store: StateStore, path: Path) -> float | None:
    value: Json = store.get(path)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def sample(store: StateStore, time: datetime) -> TemperatureSample | None:
    """What the state says now; ``None`` when it has no temperature at all."""
    taken = TemperatureSample(
        time=time.astimezone(UTC).isoformat(timespec="seconds"),
        focuser=number(store, ("focuser", "temperature")),
        ambient=number(store, ("weather", "temperature")),
        humidity=number(store, ("weather", "humidity")),
        dew_point=number(store, ("weather", "dew_point")),
    )
    if taken.focuser is None and taken.ambient is None:
        return None
    return taken


class EnvironmentLog:
    def __init__(
        self,
        store: StateStore,
        storage: StorageService,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        interval: float = SAMPLE_SECONDS,
    ) -> None:
        self._store = store
        self._storage = storage
        self._now = now
        self._interval = interval
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run(), name="environment-log")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def record(self) -> TemperatureSample | None:
        """Keep one sample now, if there is anything to keep."""
        taken = sample(self._store, self._now())
        if taken is not None:
            await anyio.to_thread.run_sync(self._storage.add_temperature, taken)
        return taken

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.record()
            except Exception:
                log.exception("cannot keep the temperatures")
