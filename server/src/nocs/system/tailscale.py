"""Tailscale on the box: what ``tailscale status`` and ``tailscale whois`` say, and
joining or leaving a tailnet.

nocsd reads the status and asks who a peer is itself: tailscaled answers those for any
local user. Joining (``tailscale login``) and leaving need root or tailscaled's operator,
so they are nocs-system operations (group ``tailscale``), on the appliance.

The box joins with ``--accept-dns=false``: it needs no tailnet names itself, and a
tailnet that overrides DNS would leave it resolving nothing at a site with no internet.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from dataclasses import dataclass
from typing import Literal, cast

import anyio
import anyio.abc

from nocs.system.protocol import HelperError, Message

log = logging.getLogger("nocs.system")

CLI = "tailscale"
TIMEOUT = 5.0
"""Seconds a ``tailscale`` command gets to answer; tailscaled answers in milliseconds."""
LOGIN_TIMEOUT = 600
"""Seconds ``tailscale login`` waits for the owner to sign in, in the background."""
LINK_WAIT = 20.0
"""Seconds the login operation waits for the sign-in link (from Tailscale's servers)."""

_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")

type BackendState = Literal["running", "needs_login", "needs_approval", "stopped", "starting"]

_STATES: dict[str, BackendState] = {
    "Running": "running",
    "NeedsLogin": "needs_login",
    "NeedsMachineAuth": "needs_approval",
    "Stopped": "stopped",
    "Starting": "starting",
    "NoState": "starting",
}


@dataclass(frozen=True, slots=True)
class Status:
    """The box on its tailnet, as ``tailscale status --json`` says."""

    state: BackendState
    auth_url: str | None = None
    """Where to sign in, while a login waits for it."""
    name: str | None = None
    """The box's MagicDNS name, e.g. ``nocs.tail1234.ts.net``."""
    ips: tuple[str, ...] = ()
    tailnet: str | None = None
    user_id: int | None = None
    """The user who owns the box's node; ``None`` for a tagged node, which has none."""
    login: str | None = None
    """That user's login name, e.g. ``someone@github``."""

    @property
    def host(self) -> str | None:
        """The short MagicDNS name, e.g. ``nocs``."""
        return self.name.split(".", 1)[0] if self.name else None

    def names_box(self, host: str | None) -> bool:
        """Whether ``host`` (a request's, without its port) is one of the box's own
        names or addresses on the tailnet."""
        if not host:
            return False
        host = host.lower().rstrip(".")
        return host in {n.lower() for n in (self.name, self.host, *self.ips) if n}


@dataclass(frozen=True, slots=True)
class Peer:
    """Another node of the tailnet, as ``tailscale whois --json`` says."""

    user_id: int | None
    """Its owner; ``None`` for a tagged node."""
    login: str
    device: str
    """The node's name, e.g. ``pixel-8``."""


def is_tailnet_address(address: str | None) -> bool:
    """Whether ``address`` is one Tailscale gives nodes (100.64.0.0/10, fd7a:115c:a1e0::/48)."""
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip in (_TAILNET_V4 if ip.version == 4 else _TAILNET_V6)


def _field(data: object, key: str) -> object:
    """``data[key]`` where ``data`` is a JSON object, else ``None``."""
    return cast(dict[str, object], data).get(key) if isinstance(data, dict) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _id(value: object) -> int | None:
    """A user ID: Tailscale's are positive integers."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value else None


def parse_status(data: object) -> Status | None:
    """``tailscale status --json`` read; ``None`` if it is not what Tailscale says."""
    backend = _field(data, "BackendState")
    if not isinstance(backend, str):
        return None
    state = _STATES.get(backend, "starting")
    auth_url = _text(_field(data, "AuthURL"))
    url = auth_url if auth_url is not None and auth_url.startswith("https://") else None
    me = _field(data, "Self")
    if state != "running" or me is None:
        return Status(state, auth_url=url)
    user_id = None if _field(me, "Tags") else _id(_field(me, "UserID"))
    profile = _field(_field(data, "User"), str(user_id)) if user_id is not None else None
    dns = _text(_field(me, "DNSName"))
    ips = _field(me, "TailscaleIPs")
    return Status(
        state,
        auth_url=url,
        name=dns.rstrip(".") or None if dns is not None else None,
        ips=tuple(ip for ip in cast(list[object], ips) if isinstance(ip, str))
        if isinstance(ips, list)
        else (),
        tailnet=_text(_field(_field(data, "CurrentTailnet"), "Name")),
        user_id=user_id,
        login=_text(_field(profile, "LoginName")),
    )


def parse_whois(data: object) -> Peer | None:
    """``tailscale whois --json`` read; ``None`` if it is not what Tailscale says."""
    node, profile = _field(data, "Node"), _field(data, "UserProfile")
    user_id, login = _id(_field(profile, "ID")), _text(_field(profile, "LoginName"))
    if node is None or user_id is None or login is None:
        return None
    name = _text(_field(node, "Name"))
    device = _text(_field(node, "ComputedName")) or (name.split(".", 1)[0] if name else login)
    tagged = bool(_field(node, "Tags"))
    return Peer(user_id=None if tagged else user_id, login=login, device=device)


async def _json(*args: str, cli: str) -> object:
    """A ``tailscale`` command's JSON output; ``None`` if there is no Tailscale here,
    tailscaled does not answer, or the command fails (``whois`` of a stranger)."""
    with anyio.move_on_after(TIMEOUT):
        try:
            result = await anyio.run_process([cli, *args], check=False)
        except FileNotFoundError:
            return None
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
    log.warning("tailscale %s did not answer in %.0f s", args[0], TIMEOUT)
    return None


async def status(cli: str = CLI) -> Status | None:
    """The box on its tailnet; ``None`` where there is no Tailscale, or tailscaled is not
    running."""
    return parse_status(await _json("status", "--json", "--peers=false", cli=cli))


async def whois(address: str, cli: str = CLI) -> Peer | None:
    """Who the node at ``address`` is; ``None`` if it is not on the box's tailnet."""
    if not is_tailnet_address(address):
        return None
    return parse_whois(await _json("whois", "--json", address, cli=cli))


class Tailscale:
    """nocs-system's side: join a tailnet (``tailscale.login``) and leave it
    (``tailscale.logout``). ``tailscale login`` runs in the background until the owner
    signs in with the link it gets, or gives up after ``LOGIN_TIMEOUT``."""

    def __init__(self, cli: str = CLI, link_wait: float = LINK_WAIT) -> None:
        self._cli = cli
        self._link_wait = link_wait
        self._tasks: anyio.abc.TaskGroup | None = None
        self._login: anyio.CancelScope | None = None

    async def run(self) -> None:
        async with anyio.create_task_group() as tasks:
            self._tasks = tasks
            try:
                await anyio.sleep_forever()
            finally:
                self._tasks = None

    async def login(self, args: Message) -> Message:
        """Start joining a tailnet; the sign-in link, once Tailscale's servers give one."""
        _no_args(args)
        current = await status(self._cli)
        if current is None:
            raise HelperError("failed", "Tailscale is not running on this box")
        if current.state == "running":
            raise HelperError("invalid", "the box is on a tailnet already: log out first")
        if self._login is None:
            if self._tasks is None:
                raise HelperError("failed", "nocs-system is not ready for Tailscale yet")
            await self._tasks.start(self._sign_in)
        with anyio.move_on_after(self._link_wait):
            while True:
                now = await status(self._cli)
                if now is not None and (now.auth_url or now.state in ("running", "needs_approval")):
                    return {"auth_url": now.auth_url, "state": now.state}
                await anyio.sleep(0.5)
        if self._login is not None:
            self._login.cancel()
        raise HelperError(
            "failed", "Tailscale gave no sign-in link: the box needs the internet to join"
        )

    async def logout(self, args: Message) -> Message:
        """Leave the tailnet: the box's node is removed from it."""
        _no_args(args)
        if self._login is not None:
            self._login.cancel()
        try:
            result = await anyio.run_process([self._cli, "logout"], check=False)
        except FileNotFoundError as e:
            raise HelperError("failed", "Tailscale is not installed") from e
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip()
            raise HelperError("failed", f"tailscale logout: {detail or result.returncode}")
        log.info("left the tailnet")
        return {}

    async def _sign_in(self, *, task_status: anyio.abc.TaskStatus[None]) -> None:
        argv = [self._cli, "login", "--accept-dns=false", f"--timeout={LOGIN_TIMEOUT}s"]
        with anyio.CancelScope() as scope:
            self._login = scope
            task_status.started()
            try:
                result = await anyio.run_process(argv, check=False)
            except FileNotFoundError:
                log.warning("tailscale is not installed")
                return
            finally:
                self._login = None
            if result.returncode == 0:
                log.info("joined a tailnet")
            else:
                detail = result.stderr.decode(errors="replace").strip()
                log.info("tailscale login ended: %s", detail or result.returncode)


def _no_args(args: Message) -> None:
    if args:
        raise HelperError("invalid", f"unexpected arguments: {', '.join(sorted(args))}")
