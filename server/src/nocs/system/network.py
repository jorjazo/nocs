"""The appliance's Wi-Fi: access point, station, and the fallback between them
(ADR 0028), through NetworkManager.

One actor, ``Network.run``, owns the Wi-Fi: every ``TICK`` seconds, or as soon as
an operation asks, it looks at the device and decides.

- At boot, known networks get ``BOOT_GRACE`` seconds; then the access point starts.
- A station that loses its network for ``LOST_GRACE`` seconds gives way to the
  access point.
- As an access point, it looks for known networks every ``RETRY_STATIONS``
  seconds, and only while no client is associated: a phone on it is never cut off.
- The owner can pin either mode.

Connections are NetworkManager keyfiles that nocs-system writes itself (mode
0600), so that no password ever appears on a command line. Settings (the pinned
mode, the country, the access point's name and password, the last join) live in
a JSON file of nocs-system's (mode 0600): the password is never sent to nocsd.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import anyio
import anyio.to_thread

from nocs.system.protocol import HelperError, Message

log = logging.getLogger("nocs.system")

TICK = 10.0
BOOT_GRACE = 60.0
LOST_GRACE = 30.0
RETRY_STATIONS = 300.0
JOIN_WAIT = 45
"""Seconds NetworkManager gets to join a network before the access point comes back."""
JOIN_DELAY = 2.0
"""Seconds before joining, so that the reply reaches the phone on the access point."""
AP_ID = "nocs-ap"
AP_ADDRESS = "10.42.0.1"
DEFAULT_PASSWORD = "nocs-setup"
"""The access point's password until the first run changes it (printed in the quick start)."""
COUNTRY_ANYWHERE = "00"

type Pin = Literal["auto", "ap", "station"]


@dataclass(slots=True)
class Settings:
    pin: Pin = "auto"
    country: str = COUNTRY_ANYWHERE
    ap_ssid: str | None = None
    """``None``: ``NOCS-xxxx`` from the Pi's serial number."""
    ap_password: str = DEFAULT_PASSWORD
    last_join: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class Paths:
    state: Path = Path("/var/lib/nocs-system/network.json")
    connections: Path = Path("/etc/NetworkManager/system-connections")
    dnsmasq: Path = Path("/etc/NetworkManager/dnsmasq-shared.d/nocs.conf")
    serial: Path = Path("/proc/device-tree/serial-number")


@dataclass(slots=True)
class Device:
    exists: bool = False
    state: str = "unavailable"
    connection: str | None = None
    ethernet: bool = False

    @property
    def mode(self) -> Literal["ap", "station", "none"]:
        if self.state != "connected" or self.connection is None:
            return "none"
        return "ap" if self.connection == AP_ID else "station"


@dataclass(slots=True)
class _Timers:
    started: float
    lost_since: float | None = None
    last_try: float = float("-inf")
    booting: bool = True
    pending_join: tuple[str, str | None] | None = None
    pending_ap: bool = False
    """New access point settings, to apply if it is on."""
    wake: anyio.Event = field(default_factory=anyio.Event)


# -- validation -------------------------------------------------------------------

_COUNTRY = re.compile(r"[A-Z]{2}")


def check_ssid(ssid: object) -> str:
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32:
        raise HelperError("invalid", "a network name is 1 to 32 bytes")
    if any(c in ssid for c in ";\\") or any(ord(c) < 32 for c in ssid):
        raise HelperError("invalid", "a network name has no control characters, ';' or '\\'")
    return ssid


def check_password(password: object) -> str:
    if not isinstance(password, str) or not 8 <= len(password) <= 63:
        raise HelperError("invalid", "a Wi-Fi password is 8 to 63 characters")
    if not password.isascii() or any(ord(c) < 32 for c in password):
        raise HelperError("invalid", "a Wi-Fi password is printable ASCII")
    return password


def check_country(country: object) -> str:
    if not isinstance(country, str) or not (_COUNTRY.fullmatch(country) or country == "00"):
        raise HelperError("invalid", "a country is two letters (ISO 3166), e.g. CL")
    return country


# -- NetworkManager -------------------------------------------------------------


def split_terse(line: str) -> list[str]:
    """``nmcli -t`` fields: separated by ':', with ':' and '\\' escaped by '\\'."""
    fields: list[str] = []
    current, escaped = "", False
    for char in line:
        if escaped:
            current, escaped = current + char, False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append(current)
            current = ""
        else:
            current += char
    fields.append(current)
    return fields


def keyfile(name: str, ssid: str, password: str | None, *, ap: bool, interface: str) -> str:
    lines = [
        "[connection]",
        f"id={name}",
        "type=wifi",
        f"interface-name={interface}",
        f"autoconnect={'false' if ap else 'true'}",
        "",
        "[wifi]",
        f"mode={'ap' if ap else 'infrastructure'}",
        f"ssid={ssid}",
    ]
    if ap:
        lines.append("band=bg")
    if password is not None:
        lines += ["", "[wifi-security]", "key-mgmt=wpa-psk", f"psk={password}"]
    if ap:
        lines += ["", "[ipv4]", "method=shared", f"address1={AP_ADDRESS}/24", "", "[ipv6]"]
        lines.append("method=disabled")
    else:
        lines += ["", "[ipv4]", "method=auto", "", "[ipv6]", "method=auto"]
    return "\n".join(lines) + "\n"


def station_id(ssid: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", ssid)[:20]
    return f"nocs-{slug}-{hashlib.sha256(ssid.encode()).hexdigest()[:6]}"


class Network:
    def __init__(
        self,
        paths: Paths | None = None,
        interface: str = "wlan0",
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._paths = paths or Paths()
        self._interface = interface
        self._now = monotonic
        self._settings = self._load()
        self._timers = _Timers(started=monotonic())

    # -- operations --------------------------------------------------------------

    async def status(self, _: Message) -> Message:
        device = await self._device()
        known = await self._known()
        return {
            "wifi": device.exists,
            "mode": device.mode,
            "ssid": known.get(device.connection or "") if device.mode == "station" else None,
            "ethernet": device.ethernet,
            "pin": self._settings.pin,
            "country": self._settings.country,
            "ap_ssid": self._ap_ssid(),
            "ap_default_password": self._settings.ap_password == DEFAULT_PASSWORD,
            "ap_clients": await self._clients() if device.mode == "ap" else 0,
            "known": sorted(set(known.values())),
            "joining": self._timers.pending_join[0] if self._timers.pending_join else None,
            "last_join": self._settings.last_join,
        }

    async def join(self, args: Message) -> Message:
        """Accepted at once; the box joins in a moment, and the phone must follow it."""
        if set(args) - {"ssid", "password"}:
            raise HelperError("invalid", "the arguments are {ssid, password}")
        ssid = check_ssid(args.get("ssid"))
        password = args.get("password")
        if password is not None:
            password = check_password(password)
        self._timers.pending_join = (ssid, password)
        self._timers.wake.set()
        return {"accepted": True}

    async def forget(self, args: Message) -> Message:
        ssid = check_ssid(args.get("ssid"))
        for name, known in (await self._known()).items():
            if known == ssid:
                await _nmcli("connection", "delete", "id", name)
        return {}

    async def access_point(self, args: Message) -> Message:
        """Name, password and country of the access point; applied in a moment if it is
        on (after the reply, which then still reaches a phone on it)."""
        if not args or set(args) - {"ssid", "password", "country"}:
            raise HelperError("invalid", "the arguments are {ssid?, password?, country?}")
        if "ssid" in args:
            self._settings.ap_ssid = check_ssid(args["ssid"])
        if "password" in args:
            self._settings.ap_password = check_password(args["password"])
        if "country" in args:
            self._settings.country = check_country(args["country"])
        self._save()
        self._timers.pending_ap = True
        self._timers.wake.set()
        return {}

    async def set_mode(self, args: Message) -> Message:
        pin = args.get("pin")
        if pin not in ("auto", "ap", "station") or set(args) != {"pin"}:
            raise HelperError("invalid", "the arguments are {pin: auto, ap or station}")
        self._settings.pin = pin
        self._save()
        self._timers.wake.set()
        return {}

    # -- the actor ---------------------------------------------------------------

    async def run(self) -> None:
        await self._set_country()
        while True:
            try:
                await self.tick()
            except HelperError as e:
                log.warning("network: %s", e)
            except Exception:  # the actor must outlive any one bad tick
                log.exception("network: tick failed")
            with anyio.move_on_after(TICK):
                await self._timers.wake.wait()
            self._timers.wake = anyio.Event()

    async def tick(self) -> None:
        timers, now = self._timers, self._now()
        if timers.pending_join is not None:
            ssid, password = timers.pending_join
            await anyio.sleep(JOIN_DELAY)
            try:
                await self._join(ssid, password)
            finally:
                timers.pending_join = None
            return
        device = await self._device()
        if not device.exists:
            return
        if timers.pending_ap:
            timers.pending_ap = False
            if device.mode == "ap":
                await anyio.sleep(JOIN_DELAY)
                log.info("restarting the access point with its new settings")
                await self._start_ap()
                return
        pin = self._settings.pin
        if pin == "ap":
            if device.mode != "ap":
                await self._start_ap()
            return
        if pin == "station":
            if device.mode == "ap":
                await _nmcli("connection", "down", "id", AP_ID)
            return
        if device.mode == "station":
            timers.lost_since, timers.booting = None, False
            return
        if device.mode == "ap":
            if now - timers.last_try >= RETRY_STATIONS and await self._clients() == 0:
                timers.last_try = now
                await self._try_known()
            return
        if timers.lost_since is None:
            timers.lost_since = timers.started if timers.booting else now
        grace = BOOT_GRACE if timers.booting else LOST_GRACE
        if now - timers.lost_since >= grace:
            log.info("no known network for %.0f s: starting the access point", grace)
            timers.booting, timers.lost_since = False, None
            await self._start_ap()

    # -- steps -------------------------------------------------------------------

    async def _join(self, ssid: str, password: str | None) -> None:
        name = station_id(ssid)
        path = self._paths.connections / f"{name}.nmconnection"
        await anyio.to_thread.run_sync(
            _write_secret,
            path,
            keyfile(name, ssid, password, ap=False, interface=self._interface),
        )
        await _nmcli("connection", "load", str(path))
        log.info("joining %r", ssid)
        try:
            await _nmcli("--wait", str(JOIN_WAIT), "connection", "up", "id", name)
        except HelperError as e:
            log.warning("cannot join %r: %s", ssid, e)
            self._record_join(ssid, str(e))
            await _nmcli("connection", "delete", "id", name, check=False)
            await self._start_ap()
            return
        self._record_join(ssid, None)

    async def _try_known(self) -> None:
        known = await self._known()
        if not known:
            return
        visible = set(
            (
                await _nmcli(
                    "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes", check=False
                )
            ).splitlines()
        )
        for name, ssid in known.items():
            if ssid in visible:
                log.info("%r is in range: leaving the access point to join it", ssid)
                try:
                    await _nmcli("--wait", str(JOIN_WAIT), "connection", "up", "id", name)
                except HelperError as e:
                    log.info("cannot join %r: %s", ssid, e)
                    await self._start_ap()
                return

    async def _start_ap(self) -> None:
        self._timers.pending_ap = False  # it starts with the settings as they are now
        await self._set_country()
        await anyio.to_thread.run_sync(self._write_ap)
        await _nmcli("connection", "load", str(self._paths.connections / f"{AP_ID}.nmconnection"))
        await _nmcli("--wait", "20", "connection", "up", "id", AP_ID)

    def _write_ap(self) -> None:
        settings = self._settings
        _write_secret(
            self._paths.connections / f"{AP_ID}.nmconnection",
            keyfile(
                AP_ID, self._ap_ssid(), settings.ap_password, ap=True, interface=self._interface
            ),
        )
        # Phones that ask DNS rather than mDNS find the box by the name they use at home.
        host = socket.gethostname()
        self._paths.dnsmasq.parent.mkdir(parents=True, exist_ok=True)
        self._paths.dnsmasq.write_text(
            f"address=/{host}.local/{AP_ADDRESS}\naddress=/{host}/{AP_ADDRESS}\n"
        )

    async def _set_country(self) -> None:
        if self._settings.country != COUNTRY_ANYWHERE:
            await _run("iw", "reg", "set", self._settings.country, check=False)

    async def _device(self) -> Device:
        output = await _nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        device = Device()
        for line in output.splitlines():
            fields = split_terse(line)
            if len(fields) < 4:
                continue
            name, kind, state, connection = fields[:4]
            if name == self._interface:
                device = Device(True, state.split(" ")[0], connection or None, device.ethernet)
            elif kind == "ethernet" and state == "connected":
                device.ethernet = True
        return device

    async def _known(self) -> dict[str, str]:
        """Station connections by NetworkManager id, with their network names."""
        output = await _nmcli("-t", "-f", "NAME,TYPE", "connection", "show")
        known: dict[str, str] = {}
        for line in output.splitlines():
            fields = split_terse(line)
            if len(fields) < 2 or fields[1] != "802-11-wireless" or fields[0] == AP_ID:
                continue
            details = await _nmcli(
                "-g",
                "802-11-wireless.ssid,802-11-wireless.mode",
                "connection",
                "show",
                "id",
                fields[0],
            )
            values = split_terse(details.strip())
            if values and (len(values) < 2 or values[1] != "ap"):
                known[fields[0]] = values[0]
        return known

    async def _clients(self) -> int:
        output = await _run("iw", "dev", self._interface, "station", "dump", check=False)
        return sum(1 for line in output.splitlines() if line.startswith("Station "))

    def _ap_ssid(self) -> str:
        if self._settings.ap_ssid:
            return self._settings.ap_ssid
        try:
            serial = self._paths.serial.read_text().strip("\0\n ")
        except OSError:
            serial = ""
        return f"NOCS-{(serial[-4:] or '0000').upper()}"

    def _record_join(self, ssid: str, error: str | None) -> None:
        self._settings.last_join = {
            "ssid": ssid,
            "ok": error is None,
            "error": error,
            "at": time.time(),
        }
        self._save()

    def _load(self) -> Settings:
        try:
            data = json.loads(self._paths.state.read_text())
            return Settings(**{k: v for k, v in data.items() if k in Settings.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return Settings()

    def _save(self) -> None:
        _write_secret(self._paths.state, json.dumps(asdict(self._settings), indent=2) + "\n")


def _write_secret(path: Path, content: str) -> None:
    """Write a file only root can read, replacing the old one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = path.with_name(f".{path.name}.new")
    fd = os.open(new, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(content)
    new.replace(path)


async def _run(*argv: str, check: bool = True) -> str:
    try:
        result = await anyio.run_process(list(argv), check=False)
    except FileNotFoundError as e:
        if check:
            raise HelperError("failed", f"{argv[0]} is not installed") from e
        return ""
    if check and result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise HelperError("failed", f"{argv[0]}: {detail or f'exit status {result.returncode}'}")
    return result.stdout.decode(errors="replace")


async def _nmcli(*args: str, check: bool = True) -> str:
    return await _run("nmcli", *args, check=check)
