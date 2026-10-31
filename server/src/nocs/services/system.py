"""The box itself, through nocs-system (ADR 0027): reboot, power off, host name.

State under ``("system",)``::

    {hostname, helper, operations, error}

nocsd reads what needs no privileges (the host name) itself; ``operations`` lists
what nocs-system performs here, which is nothing on a PC unless its owner enables
it. Rebooting or powering off is refused while a job runs, unless forced: it would
end the exposure, the slew or the sequence.
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path

import anyio

from nocs.jobs import JobManager
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


class SystemBusyError(Exception):
    """A reboot or power off would interrupt running work."""

    def __init__(self, kinds: list[str]) -> None:
        super().__init__(f"{', '.join(kinds)} running: stop it first, or force")
        self.kinds = kinds


class OperationUnavailableError(Exception):
    """nocs-system does not perform this operation here."""


class SystemService:
    def __init__(self, store: StateStore, jobs: JobManager, socket_path: Path) -> None:
        self._store = store
        self._jobs = jobs
        self._socket = socket_path
        self._operations: list[str] = []
        self._helper = False
        self._error: str | None = None
        self._published: dict[str, Json] | None = None
        self._publish()

    async def run(self) -> None:
        """Keep the list of operations current until cancelled."""
        while True:
            await self.refresh()
            await anyio.sleep(REFRESH if self._helper else RETRY)

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

    async def reboot(self, *, force: bool = False) -> None:
        await self._power("power.reboot", force)

    async def power_off(self, *, force: bool = False) -> None:
        await self._power("power.poweroff", force)

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
        }
        if state != self._published:  # refreshed every minute, mostly unchanged
            self._published = state
            self._store.set(ROOT, state)
