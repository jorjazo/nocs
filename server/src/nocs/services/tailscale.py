"""Tailscale: the box on a tailnet, and pairing the owner's devices without the passphrase.

State under ``("tailscale",)``: ``None`` where Tailscale is not installed or tailscaled
is not running, else ``{state, signing_in, name, tailnet, user, ips}``, read every few
seconds (more often while a sign-in is pending). The sign-in link is not in it: whoever
opens it first puts the box on their own tailnet, and the state reaches the diagnostics
bundle. Only the owner who asks to join gets it.

A request from a node of the tailnet is the owner's when Tailscale says that node
belongs to the user who owns the box's node, neither node is tagged, and the request
names the box by its MagicDNS name or tailnet address: a page on another domain rebound
to the box's address cannot pair through the owner's browser that way. A connection from
the box itself (its own tailnet address, whose node is the owner's too) is not one. Such
a device may pair without the passphrase, once there is one.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import anyio

from nocs.state import Json, StateStore
from nocs.system import tailscale
from nocs.system.client import TIMEOUT as HELPER_TIMEOUT
from nocs.system.protocol import Message
from nocs.system.tailscale import Peer, Status

log = logging.getLogger(__name__)

ROOT = ("tailscale",)
POLL = 10.0
"""Seconds between readings of the status."""
PENDING_POLL = 2.0
"""Seconds between readings while a sign-in is pending, so that the app sees it end."""
FRESH = 30.0
"""Seconds a reading is good for when a request asks whether its peer is the owner."""

LOGIN_TIMEOUT = tailscale.LINK_WAIT + 2 * tailscale.TIMEOUT
"""Seconds nocs-system gets for ``tailscale.login``: it waits for the link itself."""

type Perform = Callable[[str, Message, float], Awaitable[Message]]


class TailscaleService:
    def __init__(self, store: StateStore, perform: Perform, cli: str = tailscale.CLI) -> None:
        self._store = store
        self._perform = perform
        """nocs-system's operations (``SystemService.perform``)."""
        self._cli = cli
        self._status: Status | None = None
        self._read_at = -FRESH
        self._published: Json = None
        self._changed: anyio.Event | None = None
        store.set(ROOT, None)

    async def run(self) -> None:
        """Keep the state current until cancelled."""
        while True:
            self._changed = anyio.Event()
            await self.read()
            pending = self._status is not None and (
                self._status.auth_url is not None
                or self._status.state in ("starting", "needs_approval")
            )
            with anyio.move_on_after(PENDING_POLL if pending else POLL):
                await self._changed.wait()

    async def read(self) -> Status | None:
        self._status = await tailscale.status(self._cli)
        self._read_at = anyio.current_time()
        state = _state(self._status)
        if state != self._published:
            self._published = state
            self._store.set(ROOT, state)
        return self._status

    async def login(self) -> str | None:
        """Start joining a tailnet (or ask again while it waits): the link where the
        owner signs in, ``None`` if Tailscale needs none (an admin's approval)."""
        result = await self._perform("tailscale.login", {}, LOGIN_TIMEOUT)
        await self.read()
        self._wake()
        url = result.get("auth_url")
        return url if isinstance(url, str) and url.startswith("https://") else None

    async def logout(self) -> None:
        await self._perform("tailscale.logout", {}, HELPER_TIMEOUT)
        await self.read()
        self._wake()

    def _wake(self) -> None:
        """Read again sooner: a sign-in may be pending now."""
        if self._changed is not None:
            self._changed.set()

    async def owner(self, address: str | None, host: str | None) -> Peer | None:
        """The owner's device making a request from ``address`` to ``host`` (its Host
        header), if Tailscale says it is one; else ``None``."""
        if address is None or not tailscale.is_tailnet_address(address):
            return None
        box = self._status
        if box is None or anyio.current_time() - self._read_at > FRESH:
            box = await self.read()
        if box is None or box.state != "running" or box.user_id is None:
            return None
        if box.is_box(address):  # a process on the box itself
            return None
        if not box.names_box(_hostname(host)):
            return None
        peer = await tailscale.whois(address, self._cli)
        if peer is None or peer.user_id != box.user_id:
            return None
        return peer


def _hostname(host: str | None) -> str | None:
    """A Host header without its port (and an IPv6 address without its brackets)."""
    if not host:
        return None
    try:
        return urlsplit(f"//{host}").hostname
    except ValueError:
        return None


def _state(status: Status | None) -> Json:
    if status is None:
        return None
    return {
        "state": status.state,
        "signing_in": status.auth_url is not None,
        "name": status.name,
        "tailnet": status.tailnet,
        "user": status.login,
        "ips": list[Json](status.ips),
    }
