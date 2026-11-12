"""The box itself: its health, and through nocs-system (ADR 0027) reboot, power off
and host name.

State under ``("system",)``::

    {hostname, helper, operations, error, health, login}

nocsd reads what needs no privileges itself: the host name and the health
(``nocs.services.health``), sampled every few seconds and rounded so that the state
changes only when something does. ``operations`` lists what nocs-system performs
here, which is nothing on a PC unless its owner enables it. Rebooting or powering
off is refused while a job runs, unless forced: it would end the exposure, the slew
or the sequence.

``login`` is the appliance's login user (ADR 0043) and whether its password is set:
read from nocs-system when it answers, and after each attempt to set it, which says
``failed`` until one succeeds. Never the password, nor why it failed (the log says).
"""

from __future__ import annotations

import logging
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

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
NETWORK = 10.0
"""Seconds between readings of the Wi-Fi's state, where nocs-system manages it."""
NETWORK_ROOT = ("network",)
SCAN_TIMEOUT = 30.0
"""Seconds a Wi-Fi scan gets; nocs-system gives NetworkManager 20 of them."""
UPDATES_ROOT = ("updates",)
SHARE_ROOT = ("share",)
LOGIN_PASSWORD = "account.password"
"""Sets the appliance's login password: only nocs-appliance enables it (ADR 0043)."""
LOGIN_STATUS = "account.status"
"""Whether the login user has a password."""


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
        self._share: Json = None
        self._network: Json = None
        self._updates: Json = None
        self._login: dict[str, Json] | None = None
        """The login user and whether it has a password, as last read; None where there
        is no login."""
        self._login_error: str | None = None
        """Why the login's status could not be read, as last logged."""
        self._login_failed = False
        """The last attempt to set the login's password in this run failed."""
        self._publish()
        store.set(NETWORK_ROOT, None)
        store.set(UPDATES_ROOT, None)

    async def run(self) -> None:
        """Keep the health and the list of operations current until cancelled."""
        next_hello = next_network = 0.0
        while True:
            if anyio.current_time() >= next_hello:
                await self.refresh()
                next_hello = anyio.current_time() + (REFRESH if self._helper else RETRY)
            await self.sample()
            if anyio.current_time() >= next_network:
                await self.read_network()
                await self.read_updates()
                await self.read_share()
                next_network = anyio.current_time() + NETWORK
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
            await self.read_login()
        self._publish()

    async def read_login(self) -> None:
        """Read whether the login user has a password (ADR 0043). Only once nocs-system
        answered: while it is down, the last reading stands."""
        if not self.offers(LOGIN_STATUS):
            self._login = None
        else:
            try:
                status = await client.call(LOGIN_STATUS, socket=self._socket)
            except HelperUnavailableError as e:
                log.info("cannot read the login user's password status: %s", e)
            except HelperError as e:
                if self._login is not None or self._login_error != str(e):
                    log.warning("cannot tell whether the login user has a password: %s", e)
                self._login, self._login_error = None, str(e)
            else:
                self._login_error = None
                self._login = {
                    "user": str(status.get("user", "")),
                    "password": "set" if status.get("password") == "set" else "locked",
                }
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

    async def read_network(self) -> None:
        """Publish the network's state (ADR 0028), or ``None`` where NOCS does not manage it."""
        state: Json = None
        if self.offers("network.status"):
            try:
                state = _network_state(await client.call("network.status", socket=self._socket))
            except (HelperUnavailableError, HelperError) as e:
                log.info("cannot read the network's state: %s", e)
                return
        if state != self._network:
            self._network = state
            self._store.set(NETWORK_ROOT, state)

    async def network(self, op: str, args: Message) -> None:
        """``network.join``, ``forget``, ``access_point`` or ``mode``; then read the state."""
        if not op.startswith("network.") or op == "network.status":
            raise ValueError(f"not a network operation: {op}")
        await self._call(op, args)
        await self.read_network()

    async def scan_networks(self) -> list[Message]:
        """The Wi-Fi networks in range, strongest first: a scan made now (ADR 0028)."""
        result = await self._call("network.scan", {}, timeout=SCAN_TIMEOUT)
        networks = result.get("networks")
        return [
            cast(Message, n)
            for n in cast(list[object], networks if isinstance(networks, list) else [])
            if isinstance(n, dict)
        ]

    async def read_updates(self) -> None:
        """Publish what nocs-system says of updates (ADR 0025); ``None`` where it installs
        none (a PC, whose owner updates it as usual)."""
        state: Json = None
        if self.offers("update.status"):
            try:
                state = _updates_state(await client.call("update.status", socket=self._socket))
            except (HelperUnavailableError, HelperError) as e:
                log.info("cannot read the state of updates: %s", e)
                return
        if state != self._updates:
            self._updates = state
            self._store.set(UPDATES_ROOT, state)

    async def read_share(self) -> None:
        """Publish the SMB share's state (ADR 0039), ``None`` where there is none (a PC).
        While it is on, nocs-system first shares what is mounted now: a drive pulled out
        without ejecting leaves the share within one reading."""
        state: Json = None
        if self.offers("share.status"):
            try:
                if isinstance(self._share, dict) and self._share.get("on"):
                    await client.call("share.refresh", socket=self._socket)
                state = _share_state(await client.call("share.status", socket=self._socket))
            except (HelperUnavailableError, HelperError) as e:
                log.info("cannot read the SMB share's state: %s", e)
                return
        if state != self._share:
            self._share = state
            self._store.set(SHARE_ROOT, state)

    async def share(self, on: bool) -> None:
        """Switch the SMB share on or off; it does not touch a session, so a running job
        does not stop it."""
        log.info("switching the SMB share %s", "on" if on else "off")
        await self._call("share.enable", {"on": on})
        await self.read_share()

    async def set_login_password(self, passphrase: str) -> None:
        """Make the owner passphrase the password of the appliance's login user, for SSH
        and sudo (ADR 0043). Nothing where nocs-system does not do it (a PC, or no
        nocs-system). A failure is logged, never raised: the passphrase is the app's
        either way, and the state's login says ``failed``. The passphrase itself is
        never logged nor kept."""
        if not self.offers(LOGIN_PASSWORD):
            await self.refresh()  # nocs-system may have started since the last look
            if not self.offers(LOGIN_PASSWORD):
                if self._login is not None:  # a login, but nocs-system is down
                    log.warning(
                        "the login user's password is not the owner passphrase: %s",
                        self._error or "nocs-system does not set it",
                    )
                    self._login_failed = True
                    self._publish()
                return
        try:
            result = await client.call(
                LOGIN_PASSWORD, {"password": passphrase}, socket=self._socket
            )
        except (HelperUnavailableError, HelperError) as e:
            log.warning("the login user's password is not the owner passphrase: %s", e)
            self._login_failed = True
        else:
            log.info(
                "the password of the login user %s is the owner passphrase now",
                result.get("user"),
            )
            self._login_failed = False
        await self.read_login()

    async def update(self, task: str, *, force: bool = False) -> None:
        """Check for updates, install them or go back to the previous NOCS. Installing
        restarts nocsd and maybe indiserver and PHD2: refused while a job runs, unless
        forced."""
        if task not in ("check", "install", "rollback"):
            raise ValueError(f"not an update task: {task}")
        if task != "check" and not force and (kinds := self._jobs.active()):
            raise SystemBusyError(kinds)
        await self._call(f"update.{task}", {})
        await self.read_updates()

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

    async def _call(
        self, op: str, args: Message | None = None, *, timeout: float = client.TIMEOUT
    ) -> Message:
        if op not in self._operations:
            await self.refresh()  # nocs-system may have started since the last look
        if op not in self._operations:
            reason = self._error or "it is switched off in /etc/nocs/system.conf"
            raise OperationUnavailableError(f"NOCS cannot do {op} on this computer: {reason}")
        try:
            return await client.call(op, args, socket=self._socket, timeout=timeout)
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
            "login": None
            if self._login is None
            else self._login | ({"password": "failed"} if self._login_failed else {}),
        }
        if state != self._published:  # refreshed every minute, mostly unchanged
            self._published = state
            self._store.set(ROOT, state)


def _network_state(status: Message) -> Json:
    """nocs-system's network status as the state shows it: the time of the last join in
    ISO 8601, nothing it does not know."""
    last = status.get("last_join")
    if isinstance(last, dict):
        join = cast(dict[str, object], last)
        at = join.get("at")
        last_join: Json = {
            "ssid": str(join.get("ssid", "")),
            "ok": bool(join.get("ok")),
            "error": join["error"] if isinstance(join.get("error"), str) else None,  # pyright: ignore[reportAssignmentType]
            "at": datetime.fromtimestamp(at, UTC).isoformat(timespec="seconds")
            if isinstance(at, int | float)
            else None,
        }
    else:
        last_join = None
    keys = ("wifi", "mode", "ssid", "ethernet", "pin", "country", "ap_ssid")
    state: dict[str, Json] = {key: cast(Json, status.get(key)) for key in keys}
    known = status.get("known")
    state |= {
        "set_up": bool(status.get("set_up")),
        "ap_default_password": bool(status.get("ap_default_password")),
        "ap_clients": int(cast(int, status.get("ap_clients") or 0)),
        "known": [k for k in cast(list[object], known) if isinstance(k, str)]
        if isinstance(known, list)
        else [],
        "joining": cast(Json, status.get("joining")),
        "last_join": last_join,
    }
    return state


def _share_state(status: Message) -> Json:
    """nocs-system's share status as the state shows it."""
    shares: list[Json] = []
    listed = status.get("shares")
    if isinstance(listed, list):
        for item in cast(list[object], listed):
            if isinstance(item, dict):
                entry = cast(dict[str, object], item)
                label = entry.get("label")
                shares.append(
                    {
                        "name": str(entry.get("name", "")),
                        "volume": str(entry.get("volume", "")),
                        "label": label if isinstance(label, str) else None,
                    }
                )
    clients = status.get("clients")
    return {
        "on": bool(status.get("on")),
        "running": bool(status.get("running")),
        "shares": shares,
        "clients": clients if isinstance(clients, int) and not isinstance(clients, bool) else 0,
    }


_INDI = re.compile(r"^(indi-|libindi-|libindi\d)")
_REBOOT = re.compile(r"^linux-(image|modules|raspi|firmware)")


def package_kind(name: str) -> str:
    """What a package is to the rig: NOCS itself, INDI (the PPA's ``indi-bin``,
    ``libindi1``, ``indi-3rdparty-*``…), PHD2, or the rest of the system."""
    if name in ("nocs", "nocs-appliance"):
        return "nocs"
    if _INDI.match(name):
        return "indi"
    if name == "phd2":
        return "phd2"
    return "system"


def _packages(listed: object) -> list[Json]:
    packages: list[Json] = []
    if isinstance(listed, list):
        for item in cast(list[object], listed):
            if isinstance(item, dict):
                entry = cast(dict[str, object], item)
                name = str(entry.get("name", ""))
                packages.append(
                    {
                        "name": name,
                        "from": str(entry.get("from", "")),
                        "to": str(entry.get("to", "")),
                        "kind": package_kind(name),
                        "security": entry.get("security") is True,
                        "reboot": bool(_REBOOT.match(name)),
                    }
                )
    return packages


def _updates_state(status: Message) -> Json:
    """nocs-system's update status as the state shows it, each package classified."""
    checked = status.get("checked")
    log_lines = status.get("log")
    return {
        "state": cast(Json, status.get("state")),
        "task": cast(Json, status.get("task")),
        "packages": _packages(status.get("upgradable")),
        "upgraded": _packages(status.get("upgraded")),
        "reboot_required": status.get("reboot_required") is True,
        "checked": datetime.fromtimestamp(checked, UTC).isoformat(timespec="seconds")
        if isinstance(checked, int | float)
        else None,
        "installed": cast(Json, status.get("installed")),
        "previous": cast(Json, status.get("previous")),
        "error": cast(Json, status.get("error")),
        "log": [str(line) for line in cast(list[object], log_lines)]
        if isinstance(log_lines, list)
        else [],
    }
