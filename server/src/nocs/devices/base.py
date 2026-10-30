"""Typed device facades over INDI.

A facade wraps one INDI device by name and exposes the standard INDI properties
of its kind as typed reads and awaitable commands. Commands complete when the
driver reports the property back as ``Ok`` and fail when it reports ``Alert``,
so workflows never have to reason about raw property states.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from enum import IntFlag
from typing import ClassVar, Self

from nocs.indi import (
    ConnectionLost,
    IndiClient,
    IndiEvent,
    Property,
    PropertyDeleted,
    PropertyState,
    PropertyUpdated,
)

DEFAULT_TIMEOUT = 30.0


class DeviceInterface(IntFlag):
    """Capabilities a driver declares in ``DRIVER_INFO.DRIVER_INTERFACE``."""

    GENERAL = 0
    TELESCOPE = 1 << 0
    CCD = 1 << 1
    GUIDER = 1 << 2
    FOCUSER = 1 << 3
    FILTER = 1 << 4
    DOME = 1 << 5
    GPS = 1 << 6
    WEATHER = 1 << 7
    AO = 1 << 8
    DUSTCAP = 1 << 9
    LIGHTBOX = 1 << 10
    DETECTOR = 1 << 11
    ROTATOR = 1 << 12
    SPECTROGRAPH = 1 << 13
    CORRELATOR = 1 << 14
    AUX = 1 << 15


def device_interfaces(client: IndiClient, device: str) -> DeviceInterface:
    info = client.get_property(device, "DRIVER_INFO")
    if info is None or "DRIVER_INTERFACE" not in info.elements:
        return DeviceInterface.GENERAL
    try:
        return DeviceInterface(int(info.text("DRIVER_INTERFACE")))
    except ValueError:
        return DeviceInterface.GENERAL


class DeviceError(Exception):
    """A device rejected a command, is missing a property, or went away."""


class Device:
    """Any INDI device: connection management and command plumbing."""

    INTERFACE: ClassVar[DeviceInterface] = DeviceInterface.GENERAL
    REQUIRED: ClassVar[tuple[str, ...]] = ()
    """Properties the facade needs; drivers define them only after connecting."""

    def __init__(self, client: IndiClient, name: str) -> None:
        self.client = client
        self.name = name

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"

    @classmethod
    def find_all(cls, client: IndiClient) -> list[Self]:
        """Every device on the server whose driver declares this facade's interface."""
        return [
            cls(client, name)
            for name in sorted(client.devices)
            if cls.INTERFACE in device_interfaces(client, name)
        ]

    @property
    def interfaces(self) -> DeviceInterface:
        return device_interfaces(self.client, self.name)

    @property
    def connected(self) -> bool:
        prop = self.client.get_property(self.name, "CONNECTION")
        return prop is not None and prop.switch("CONNECT")

    async def connect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Connect the device and wait until the properties this facade needs exist."""
        try:
            # Right after a (re)connection to indiserver, devices are still being defined.
            await self.client.wait_for_property(self.name, "CONNECTION", timeout)
        except TimeoutError as e:
            raise DeviceError(f"device {self.name} not found") from e
        if not self.connected:
            await self.command(
                "CONNECTION",
                {"CONNECT": True, "DISCONNECT": False},
                timeout=timeout,
                done=lambda p: p.switch("CONNECT"),
            )
        await self.wait_ready(timeout)

    def not_ready(self) -> list[str]:
        """What the facade still waits for; subclasses add checks on values."""
        return [name for name in self.REQUIRED if not self.has(name)]

    async def wait_ready(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        try:
            await self.client.wait_for(lambda _: not self.not_ready(), timeout)
        except TimeoutError as e:
            raise DeviceError(f"{self.name} is not ready: {', '.join(self.not_ready())}") from e

    async def disconnect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        if not self.connected:
            return
        await self.command(
            "CONNECTION",
            {"CONNECT": False, "DISCONNECT": True},
            timeout=timeout,
            done=lambda p: p.switch("DISCONNECT"),
            # Drivers report a closed connection as Idle, not Ok.
            accept=frozenset({PropertyState.OK, PropertyState.IDLE}),
        )

    # -- helpers for subclasses ------------------------------------------

    def prop(self, name: str) -> Property:
        prop = self.client.get_property(self.name, name)
        if prop is None:
            raise DeviceError(f"{self.name} has no property {name}")
        return prop

    def has(self, name: str) -> bool:
        return self.client.get_property(self.name, name) is not None

    async def command(
        self,
        name: str,
        values: Mapping[str, str | float | bool],
        *,
        timeout: float = DEFAULT_TIMEOUT,
        done: Callable[[Property], bool] | None = None,
        accept: frozenset[PropertyState] = frozenset({PropertyState.OK}),
    ) -> Property:
        """Send new values and wait for the driver to report the property ``Ok``.

        ``done`` adds a condition on the updated property (e.g. a target position
        reached) for drivers that report ``Ok`` before the action is complete.
        ``accept`` widens the states that count as completion, for properties
        whose state encodes the result (e.g. tracking: ``Busy`` on, ``Idle`` off).
        """
        self.prop(name)
        return await self.send_and_wait(
            lambda: self.client.send(self.name, name, values),
            name,
            timeout=timeout,
            done=done,
            accept=accept,
        )

    async def send_and_wait(
        self,
        send: Callable[[], Awaitable[None]],
        name: str,
        *,
        timeout: float,
        done: Callable[[Property], bool] | None = None,
        accept: frozenset[PropertyState] = frozenset({PropertyState.OK}),
    ) -> Property:
        """Run ``send`` and wait for the next qualifying update of property ``name``.

        The listener is registered before sending, so an update that arrives
        immediately cannot be missed, and a stale ``Ok`` from before the command
        is never mistaken for completion.
        """
        loop = asyncio.get_running_loop()
        result: asyncio.Future[Property] = loop.create_future()

        def on_event(event: IndiEvent) -> None:
            if result.done():
                return
            match event:
                case PropertyUpdated(property=prop) if prop.key == (self.name, name):
                    if prop.state is PropertyState.ALERT:
                        detail = f": {prop.message}" if prop.message else ""
                        result.set_exception(DeviceError(f"{self.name}.{name} failed{detail}"))
                    elif prop.state in accept and (done is None or done(prop)):
                        result.set_result(prop)
                case PropertyDeleted(device=device, name=deleted) if device == self.name and (
                    deleted in (None, name)
                ):
                    result.set_exception(DeviceError(f"{self.name}.{name} was removed"))
                case ConnectionLost(reason=reason):
                    result.set_exception(DeviceError(f"lost connection to indiserver: {reason}"))
                case _:
                    pass

        remove = self.client.add_listener(on_event)
        try:
            await send()
            async with asyncio.timeout(timeout):
                return await result
        except TimeoutError as e:
            raise DeviceError(f"{self.name}.{name}: no response within {timeout:g} s") from e
        finally:
            remove()
