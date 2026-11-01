"""The box itself: its health, and through nocs-system (ADR 0027) reboot, power off
and host name.

State under ``("system",)``::

    {hostname, helper, operations, error, health}

nocsd reads what needs no privileges itself: the host name and the health
(``nocs.services.health``), sampled every few seconds and rounded so that the state
changes only when something does. ``operations`` lists what nocs-system performs
here, which is nothing on a PC unless its owner enables it. Rebooting or powering
off is refused while a job runs, unless forced: it would end the exposure, the slew
or the sequence.
"""

from __future__ import annotations

import logging
import socket
from datetime import UTC, datetime
from pathlib import Path

import anyio
import anyio.to_thread

from nocs.jobs import JobManager
from nocs.services import diagnostics
from nocs.services.health import Health, HealthPaths, read_health, warnings
from nocs.state import Json, StateStore
from nocs.system import client
from nocs.system.client import HelperUnavailableError
from nocs.system.protocol import HELLO, HelperError, Message, validate_hostname

log = logging.getLogger(__name__)

ROOT = ("system",)
RETRY = 5.0
"""Seconds between attempts to reach nocs-system while it is not answering."""
REFRESH = 60.0
"""Seconds between checks of what nocs-system offers once it answers."""
SAMPLE = 5.0
"""Seconds between health readings."""


class SystemBusyError(Exception):
    """A reboot or power off would interrupt running work."""

    def __init__(self, kinds: list[str]) -> None:
        super().__init__(f"{', '.join(kinds)} running: stop it first, or force")
        self.kinds = kinds


class OperationUnavailableError(Exception):
    """nocs-system does not perform this operation here."""


class SystemService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        socket_path: Path,
        health_paths: HealthPaths | None = None,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._socket = socket_path
        self._health_paths = health_paths or HealthPaths()
        self._operations: list[str] = []
        self._helper = False
        self._error: str | None = None
        self._health: dict[str, Json] | None = None
        self._under_voltage_seen: str | None = None
        self._published: dict[str, Json] | None = None
        self._publish()

    async def run(self) -> None:
        """Keep the health and the list of operations current until cancelled."""
        next_hello = 0.0
        while True:
            if anyio.current_time() >= next_hello:
                await self.refresh()
                next_hello = anyio.current_time() + (REFRESH if self._helper else RETRY)
            await self.sample()
            await anyio.sleep(SAMPLE)

    async def sample(self) -> None:
        health = await anyio.to_thread.run_sync(read_health, self._health_paths)
        if health.under_voltage:
            self._under_voltage_seen = datetime.now(UTC).isoformat(timespec="seconds")
        self._health = self._rounded(health)
        self._publish()

    def _rounded(self, health: Health) -> dict[str, Json]:
        """As the app shows it: whole degrees and percent, 100 rpm, 100 MB."""

        def nearest(value: float | None, step: int) -> int | None:
            return None if value is None else round(value / step) * step

        return {
            "cpu_temperature": nearest(health.cpu_temperature, 1),
            "fan": nearest(health.fan, 100),
            "under_voltage": health.under_voltage,
            "under_voltage_seen": self._under_voltage_seen,
            "throttled": health.throttled,
            "memory_used": nearest(
                None if health.memory_used is None else health.memory_used * 100, 1
            ),
            "disk_free": nearest(health.disk_free, 100_000_000),
            "warnings": list[Json](warnings(health)),
        }

    async def refresh(self) -> None:
        try:
            hello = await client.call(HELLO, socket=self._socket)
        except (HelperUnavailableError, HelperError) as e:
            if self._helper or self._error is None:
                log.info("nocs-system: %s", e)
            self._helper, self._operations, self._error = False, [], str(e)
        else:
            operations = hello.get("operations")
            self._helper, self._error = True, None
            self._operations = (
                [op for op in operations if isinstance(op, str)]  # pyright: ignore[reportUnknownVariableType]
                if isinstance(operations, list)
                else []
            )
        self._publish()

    def offers(self, op: str) -> bool:
        """nocs-system performs ``op`` here, as far as NOCS knows."""
        return op in self._operations

    async def perform(self, op: str, args: Message) -> Message:
        """Perform ``op`` for another service (storage); errors as ``_call`` raises them."""
        return await self._call(op, args)

    async def reboot(self, *, force: bool = False) -> None:
        await self._power("power.reboot", force)

    async def power_off(self, *, force: bool = False) -> None:
        await self._power("power.poweroff", force)

    async def restart_service(self, service: str, *, force: bool = False) -> None:
        """Restart indiserver or PHD2. Restarting indiserver drops every device, so it is
        refused while a job runs, unless forced (as when it is hung, ADR 0030)."""
        if not force and (kinds := self._jobs.active()):
            raise SystemBusyError(kinds)
        log.warning("restarting %s", service)
        await self._call("services.restart", {"service": service})

    async def set_hostname(self, name: str) -> str:
        """Rename the box; the new name, as nocs-system stored it."""
        try:
            name = validate_hostname(name)
        except HelperError as e:
            raise ValueError(str(e)) from e
        result = await self._call("hostname.set", {"name": name})
        self._publish()
        stored = result.get("name")
        return stored if isinstance(stored, str) else name

    async def diagnostics(self) -> tuple[str, bytes]:
        """A zip for a bug report: its file name and its bytes."""
        state = self._store.snapshot()
        now = datetime.now(UTC)
        return await anyio.to_thread.run_sync(diagnostics.build, state, socket.gethostname(), now)

    async def _power(self, op: str, force: bool) -> None:
        if not force and (kinds := self._jobs.active()):
            raise SystemBusyError(kinds)
        log.warning("%s requested", op)
        await self._call(op)

    async def _call(self, op: str, args: Message | None = None) -> Message:
        if op not in self._operations:
            await self.refresh()  # nocs-system may have started since the last look
        if op not in self._operations:
            reason = self._error or "it is switched off in /etc/nocs/system.conf"
            raise OperationUnavailableError(f"NOCS cannot do {op} on this computer: {reason}")
        try:
            return await client.call(op, args, socket=self._socket)
        except HelperError as e:
            if e.code == "invalid":
                raise ValueError(str(e)) from e
            raise

    def _publish(self) -> None:
        state: dict[str, Json] = {
            "hostname": socket.gethostname(),
            "helper": self._helper,
            "operations": list[Json](self._operations),
            "error": self._error,
            "health": self._health,
        }
        if state != self._published:  # refreshed every minute, mostly unchanged
            self._published = state
            self._store.set(ROOT, state)
