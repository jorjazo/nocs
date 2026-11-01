"""Typed device facades over INDI.

A facade wraps one INDI device by name and exposes the standard INDI properties
of its kind as typed reads and awaitable commands. Commands complete when the
driver reports the property back as ``Ok`` and fail when it reports ``Alert``,
so workflows never have to reason about raw property states.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from enum import IntFlag
from typing import ClassVar, Self
from weakref import WeakKeyDictionary

from nocs.indi import (
    ConnectionLost,
    IndiClient,
    IndiEvent,
    MessageReceived,
    Property,
    PropertyDefined,
    PropertyDeleted,
    PropertyState,
    PropertyUpdated,
    TextElement,
)

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
SILENCE = 15.0
"""Seconds a device may send nothing while a command of its waits before it is probed."""
PROBE_TIMEOUT = 10.0
"""Seconds a probed device has to define its ``CONNECTION`` again (ADR 0030)."""
SERIAL_PROPERTIES = ("Serial Number", "SERIAL_NUMBER")
"""Where drivers publish a device's serial number; INDI has no standard property (ZWO: SN)."""


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
    OUTPUT = 1 << 16
    INPUT = 1 << 17
    POWER = 1 << 18


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


class DeviceUnresponsive(DeviceError):
    """A device stopped answering: silent or past a command's deadline, it did not
    answer a probe either (ADR 0030)."""

    def __init__(self, device: str, message: str) -> None:
        super().__init__(message)
        self.device = device


type UnresponsiveListener = Callable[[str, str], None]
_unresponsive: WeakKeyDictionary[IndiClient, list[UnresponsiveListener]] = WeakKeyDictionary()


def on_unresponsive(client: IndiClient, listener: UnresponsiveListener) -> Callable[[], None]:
    """Call ``listener(device, reason)`` whenever a facade on ``client`` finds a device
    unresponsive; returns a function that stops it."""
    listeners = _unresponsive.setdefault(client, [])
    listeners.append(listener)
    return lambda: listeners.remove(listener)


def _report_unresponsive(client: IndiClient, device: str, reason: str) -> None:
    log.warning("%s", reason)
    for listener in list(_unresponsive.get(client, ())):
        try:
            listener(device, reason)
        except Exception:
            log.exception("unresponsive listener failed")


def event_device(event: IndiEvent) -> str | None:
    """The device an event comes from, if any."""
    match event:
        case PropertyDefined(property=prop) | PropertyUpdated(property=prop):
            return prop.device
        case PropertyDeleted(device=device) | MessageReceived(device=device):
            return device
        case _:
            return None


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
                # Drivers connect on their main thread, silent until they are done.
                watch_silence=False,
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
            watch_silence=False,
        )

    @property
    def serial_number(self) -> str | None:
        """The device's serial number, when its driver publishes one."""
        for name in SERIAL_PROPERTIES:
            if not self.has(name):
                continue
            for element in self.prop(name).elements.values():
                if isinstance(element, TextElement) and element.value.strip():
                    return element.value.strip()
        return None

    @property
    def key(self) -> str:
        """The physical device, apart from profiles (ADR 0016): ``serial:<number>`` when
        its driver publishes one, else ``device:<INDI device name>``."""
        serial = self.serial_number
        return f"serial:{serial}" if serial else f"device:{self.name}"

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
        watch_silence: bool = True,
    ) -> Property:
        """Send new values and wait for the driver to report the property ``Ok``.

        ``done`` adds a condition on the updated property (e.g. a target position
        reached) for drivers that report ``Ok`` before the action is complete.
        ``accept`` widens the states that count as completion, for properties
        whose state encodes the result (e.g. tracking: ``Busy`` on, ``Idle`` off).
        ``watch_silence`` probes a device that goes quiet before the deadline
        (``supervise``), for commands its driver does not carry out on its main thread.
        """
        self.prop(name)
        return await self.send_and_wait(
            lambda: self.client.send(self.name, name, values),
            name,
            timeout=timeout,
            done=done,
            accept=accept,
            watch_silence=watch_silence,
        )

    async def send_and_wait(
        self,
        send: Callable[[], Awaitable[None]],
        name: str,
        *,
        timeout: float,
        done: Callable[[Property], bool] | None = None,
        accept: frozenset[PropertyState] = frozenset({PropertyState.OK}),
        watch_silence: bool = True,
    ) -> Property:
        """Run ``send`` and wait for the next qualifying update of property ``name``.

        The listener is registered before sending, so an update that arrives
        immediately cannot be missed, and a stale ``Ok`` from before the command
        is never mistaken for completion. Drivers often explain a failure in a
        separate message just before the ``Alert`` (the ZWO mounts' "Slew failed"); it
        becomes the error's detail when the property carries none.
        """
        loop = asyncio.get_running_loop()
        result: asyncio.Future[Property] = loop.create_future()
        messages: list[str] = []

        heard = loop.time()

        def on_event(event: IndiEvent) -> None:
            nonlocal heard
            if event_device(event) == self.name:
                heard = loop.time()
            if result.done():
                return
            match event:
                case MessageReceived(device=device, text=text) if device == self.name:
                    messages.append(text.removeprefix("[ERROR] ").strip())
                case PropertyUpdated(property=prop) if prop.key == (self.name, name):
                    if prop.state is PropertyState.ALERT:
                        reason = prop.message or "; ".join(messages[-2:])
                        detail = f": {reason}" if reason else ""
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
            return await self.supervise(
                result,
                loop.time() + timeout,
                lambda: heard,
                f"{self.name}.{name}: no response within {timeout:g} s",
                watch_silence=watch_silence,
            )
        finally:
            remove()

    async def supervise[T](
        self,
        result: asyncio.Future[T],
        deadline: float,
        heard: Callable[[], float],
        missed: str,
        *,
        watch_silence: bool = True,
    ) -> T:
        """Wait for ``result`` until ``deadline`` (event loop time), probing the device
        when it sends nothing for ``SILENCE`` seconds or the deadline passes (ADR 0030).

        ``heard`` says when the device last sent anything. A probe unanswered fails
        with ``DeviceUnresponsive``, reported to ``on_unresponsive``'s listeners; an
        answered one after the deadline fails with ``DeviceError(missed)``, and after
        a silence lets the wait go on: a quiet device is not a hung one. Without
        ``watch_silence``, only the deadline is watched.
        """
        loop = asyncio.get_running_loop()
        answered_at = loop.time()
        while not result.done():
            now = loop.time()
            last = max(heard(), answered_at)
            wake = min(deadline, last + SILENCE) if watch_silence else deadline
            if wake > now:
                await asyncio.wait({result}, timeout=wake - now)
                continue
            late = now >= deadline
            answered = await self.probe()
            if result.done():
                break
            if not answered:
                why = missed if late else f"silent for {now - last:.0f} s"
                reason = f"{self.name} is not answering ({why})"
                _report_unresponsive(self.client, self.name, reason)
                raise DeviceUnresponsive(self.name, reason)
            if late:
                raise DeviceError(missed)
            answered_at = loop.time()
        return result.result()

    async def probe(self, timeout: float | None = None) -> bool:
        """Whether the driver answers: asked for its ``CONNECTION``, it defines it again.

        indiserver answers pings itself, so only the driver's own answer proves that
        it works (ADR 0030).
        """
        loop = asyncio.get_running_loop()
        answered: asyncio.Future[None] = loop.create_future()

        def on_event(event: IndiEvent) -> None:
            match event:
                case PropertyDefined(property=prop) if (
                    prop.key == (self.name, "CONNECTION") and not answered.done()
                ):
                    answered.set_result(None)
                case _:
                    pass

        remove = self.client.add_listener(on_event)
        try:
            await self.client.get_properties(self.name, "CONNECTION")
            async with asyncio.timeout(PROBE_TIMEOUT if timeout is None else timeout):
                await answered
        except TimeoutError:
            return False
        finally:
            remove()
        return True
