"""The slew pad and its dead man's switch (ADR 0015).

The mount moves only while a client keeps saying which way. The client sends
what it holds every ``KEEPALIVE`` seconds; the pad stops the mount when the
client lets go, when nothing arrives for ``TIMEOUT`` seconds (Wi-Fi gone, app in
the background), when the connection closes or nocsd stops, and when anyone
aborts. After a stop it did not ask for, the client must let go before the pad
moves the mount again, so a pad that comes back from a dropout never resumes
by itself.

While it moves the mount, a pad holds the ``mount`` lock (a reservation, not a
job): go to, park and home are refused meanwhile, and the other way round.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import anyio

from nocs.devices import STOPPED, DeviceError, Motion, Mount

log = logging.getLogger(__name__)

KEEPALIVE = 0.25
"""How often clients repeat what they hold."""
TIMEOUT = 1.0
"""Silence after which the pad stops the mount."""
STOP_TIMEOUT = 5.0
"""Budget for stopping (and aborting if the stop fails) once the client is gone."""


@dataclass(frozen=True, slots=True)
class PadCommand:
    """What the client holds now; ``STOPPED`` to let go."""

    motion: Motion
    rate: str | None = None


@dataclass(frozen=True, slots=True)
class PadStatus:
    motion: Motion
    """What the pad is doing with the mount."""
    rate: str | None
    latched: bool
    """Stopped by NOCS: let go before moving again."""
    message: str | None
    """Why it stopped or refused, if it did."""


class PadHost(Protocol):
    """What the mount service offers its pads."""

    def mount(self) -> Mount: ...

    def reserve(self, pad: Pad) -> str:
        """Lock the mount for ``pad``; raises ``ResourceBusyError`` if something else has it."""
        ...

    def release(self, pad: Pad, token: str) -> None: ...


class Pad:
    """One client's slew pad."""

    def __init__(self, host: PadHost, client: str) -> None:
        self._host = host
        self.client = client
        """Who is at the pad (the paired device's name)."""
        self._motion = STOPPED
        self._rate: str | None = None
        self._token: str | None = None
        self._latched: str | None = None
        self._message: str | None = None
        self._lock = anyio.Lock()

    @property
    def active(self) -> bool:
        """The pad holds the mount (and may have it moving)."""
        return self._token is not None

    @property
    def status(self) -> PadStatus:
        return PadStatus(self._motion, self._rate, self._latched is not None, self._message)

    async def apply(self, command: PadCommand) -> PadStatus:
        async with self._lock:
            if not command.motion.moving:
                self._latched = None
                self._message = None
                await self._stop()
                return self.status
            if self._latched is not None:
                self._message = f"{self._latched}; let go to move again"
                return self.status
            try:
                await self._move(command)
            except Exception as e:
                # Refused (parked, busy, no mount) or failed half-way: never leave it moving.
                await self._stop()
                self._latch(str(e) or type(e).__name__)
            else:
                self._message = None
                if self._latched is not None:
                    # Aborted while the command was in flight.
                    await self._stop()
            return self.status

    async def stop(self, reason: str) -> PadStatus:
        """Stop the mount for a reason of NOCS's own (silence, closing) and latch."""
        async with self._lock:
            if self.active or self._motion.moving:
                await self._stop()
                self._latch(reason)
            return self.status

    def interrupt(self, reason: str) -> None:
        """The mount was aborted for everyone: forget the motion and latch.

        Synchronous on purpose: an abort must not wait behind a pad command.
        """
        if not self.active and not self._motion.moving:
            return
        self._latch(reason)
        self._motion = STOPPED
        self._release()

    async def _move(self, command: PadCommand) -> None:
        mount = self._host.mount()
        if self._token is None:
            self._token = self._host.reserve(self)
        if command.rate is not None and (
            command.rate != mount.slew_rate or not self._motion.moving
        ):
            if self._motion.moving:
                # Drivers apply a new rate on the next start, not to a motion under way.
                await mount.move(STOPPED)
                self._motion = STOPPED
            # At every start, even when the switch shows it already: the AM5's driver
            # shows a rate it never gave the mount (``Mount.set_slew_rate``).
            await mount.set_slew_rate(command.rate, force=True)
        self._rate = mount.slew_rate
        await mount.move(command.motion)
        self._motion = command.motion

    async def _stop(self) -> None:
        """Stop both axes (abort if that fails) and give the mount back."""
        if self._token is None and not self._motion.moving:
            return
        try:
            mount = self._host.mount()
        except Exception as e:
            log.warning("pad of %s: cannot reach the mount to stop it: %s", self.client, e)
        else:
            try:
                await mount.stop()
            except (DeviceError, ConnectionError) as e:
                log.error("pad of %s: stop failed (%s); aborting", self.client, e)
                try:
                    await mount.abort()
                except (DeviceError, ConnectionError) as e2:
                    log.critical("pad of %s: the mount may still be moving: %s", self.client, e2)
                    self._latch(f"the mount may still be moving: {e2}")
        self._motion = STOPPED
        self._release()

    def _release(self) -> None:
        if self._token is not None:
            token, self._token = self._token, None
            self._host.release(self, token)

    def _latch(self, reason: str) -> None:
        self._latched = reason
        self._message = reason


type Receive = Callable[[], Awaitable[PadCommand | None]]
"""Next command from the client; ``None`` once it is gone. Raises ValueError for junk."""
type Send = Callable[[PadStatus], Awaitable[None]]


async def drive(pad: Pad, receive: Receive, send: Send, timeout: float = TIMEOUT) -> None:
    """Feed a client's commands to ``pad`` until the client goes; stop on silence.

    The deadline runs from the last message received, so time spent sending a
    status or commanding the mount never extends it. However this ends (the
    client closes, the connection drops, the task is cancelled), the mount is
    stopped on the way out.
    """
    deadline = anyio.current_time() + timeout
    try:
        while True:
            command: PadCommand | None = None
            silent = True
            with anyio.move_on_at(deadline):
                try:
                    command = await receive()
                except ValueError as e:
                    status = await pad.stop(f"bad message: {e}")
                    await _send(send, status, deadline)
                    deadline = anyio.current_time() + timeout
                    continue
                silent = False
            if silent:
                if pad.active:
                    status = await pad.stop(f"no word from {pad.client} for {timeout:g} s")
                    await _send(send, status, anyio.current_time() + timeout)
                deadline = anyio.current_time() + timeout
                continue
            if command is None:
                return
            deadline = anyio.current_time() + timeout
            status = await pad.apply(command)
            await _send(send, status, deadline)
    finally:
        with anyio.CancelScope(shield=True), anyio.move_on_after(STOP_TIMEOUT):
            await pad.stop("the pad closed")


async def _send(send: Send, status: PadStatus, deadline: float) -> None:
    """Tell the client, but never wait past the deadline for a client that is not reading."""
    with anyio.move_on_at(deadline):
        await send(status)
