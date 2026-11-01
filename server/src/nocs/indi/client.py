"""Async INDI client over TCP.

The client keeps a live mirror of every device property the server defines and
notifies listeners of changes. It does not reconnect by itself; supervision
(backoff, reconnection) belongs to the service that owns it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from nocs.indi.properties import Property, PropertyType
from nocs.indi.protocol import (
    BlobMode,
    DefineProperty,
    DeleteProperty,
    IndiMessage,
    Message,
    PingReply,
    ProtocolError,
    SetProperty,
    StreamParser,
    apply_set,
    encode_enable_blob,
    encode_get_properties,
    encode_new_vector,
    encode_ping,
)

log = logging.getLogger(__name__)

DEFAULT_PORT = 7624
_READ_SIZE = 256 * 1024


@dataclass(frozen=True, slots=True)
class PropertyDefined:
    property: Property


@dataclass(frozen=True, slots=True)
class PropertyUpdated:
    property: Property
    elements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PropertyDeleted:
    device: str
    name: str | None


@dataclass(frozen=True, slots=True)
class MessageReceived:
    device: str | None
    timestamp: str | None
    text: str


@dataclass(frozen=True, slots=True)
class ConnectionLost:
    reason: str


type IndiEvent = (
    PropertyDefined | PropertyUpdated | PropertyDeleted | MessageReceived | ConnectionLost
)
type Listener = Callable[[IndiEvent], None]


class IndiClient:
    def __init__(self, host: str = "localhost", port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._devices: dict[str, dict[str, Property]] = {}
        self._listeners: list[Listener] = []
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._pings: dict[str, asyncio.Future[None]] = {}
        self._ping_count = 0

    # -- connection -------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self, timeout: float = 5.0, device: str | None = None) -> None:
        """Open the connection and request the properties of every device, or of one."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout
        )
        self._devices.clear()
        self._read_task = asyncio.create_task(self._read_loop(), name="indi-read")
        await self._send(encode_get_properties(device))

    async def close(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await self._writer.wait_closed()
            self._writer = None

    async def __aenter__(self) -> IndiClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # -- state ------------------------------------------------------------

    @property
    def devices(self) -> Mapping[str, Mapping[str, Property]]:
        return self._devices

    def get_property(self, device: str, name: str) -> Property | None:
        return self._devices.get(device, {}).get(name)

    def add_listener(self, listener: Listener) -> Callable[[], None]:
        """Register a listener; returns a function that removes it."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def wait_for(
        self, predicate: Callable[[IndiClient], bool], timeout: float = 10.0
    ) -> None:
        """Wait until ``predicate(client)`` holds, re-checking after every event."""
        if predicate(self):
            return
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()

        def check(event: IndiEvent) -> None:
            if done.done():
                return
            if isinstance(event, ConnectionLost):
                done.set_exception(ConnectionError(event.reason))
            elif predicate(self):
                done.set_result(None)

        remove = self.add_listener(check)
        try:
            await asyncio.wait_for(done, timeout)
        finally:
            remove()

    async def wait_for_property(self, device: str, name: str, timeout: float = 10.0) -> Property:
        await self.wait_for(lambda c: c.get_property(device, name) is not None, timeout)
        prop = self.get_property(device, name)
        assert prop is not None
        return prop

    # -- commands ---------------------------------------------------------

    async def ping(self, timeout: float = 10.0) -> float:
        """Seconds indiserver takes to answer a ping (it answers itself, whatever its
        drivers do); ``TimeoutError`` when it does not (ADR 0030)."""
        self._ping_count += 1
        uid = f"nocs-{self._ping_count}"
        answered = asyncio.get_running_loop().create_future()
        self._pings[uid] = answered
        start = asyncio.get_running_loop().time()
        try:
            await self._send(encode_ping(uid))
            async with asyncio.timeout(timeout):
                await answered
        finally:
            self._pings.pop(uid, None)
        return asyncio.get_running_loop().time() - start

    async def get_properties(self, device: str | None = None, name: str | None = None) -> None:
        await self._send(encode_get_properties(device, name))

    async def send(self, device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        """Send new element values for a known property (type taken from its definition)."""
        prop = self.get_property(device, name)
        if prop is None:
            raise KeyError(f"unknown property {device}.{name}")
        unknown = set(values) - set(prop.elements)
        if unknown:
            raise KeyError(f"unknown elements for {device}.{name}: {sorted(unknown)}")
        await self._send(encode_new_vector(prop.type, device, name, values))

    async def send_switch(self, device: str, name: str, values: Mapping[str, bool]) -> None:
        await self._send(encode_new_vector(PropertyType.SWITCH, device, name, values))

    async def send_number(self, device: str, name: str, values: Mapping[str, float]) -> None:
        await self._send(encode_new_vector(PropertyType.NUMBER, device, name, values))

    async def send_text(self, device: str, name: str, values: Mapping[str, str]) -> None:
        await self._send(encode_new_vector(PropertyType.TEXT, device, name, values))

    async def enable_blob(self, device: str, mode: BlobMode, name: str | None = None) -> None:
        await self._send(encode_enable_blob(device, mode, name))

    # -- internals --------------------------------------------------------

    async def _send(self, data: bytes) -> None:
        if self._writer is None or self._writer.is_closing():
            raise ConnectionError("not connected to indiserver")
        async with self._write_lock:
            self._writer.write(data)
            await self._writer.drain()

    async def _read_loop(self) -> None:
        assert self._reader is not None
        parser = StreamParser()
        reason = "connection closed by server"
        try:
            while data := await self._reader.read(_READ_SIZE):
                for message in parser.feed(data):
                    self._handle(message)
        except (ConnectionError, OSError) as e:
            reason = f"connection error: {e}"
        except ProtocolError as e:
            reason = f"protocol error: {e}"
            log.error("INDI %s", reason)
        if self._writer is not None:
            self._writer.close()
        self._emit(ConnectionLost(reason))

    def _handle(self, message: IndiMessage) -> None:
        match message:
            case DefineProperty(property=prop):
                if not prop.device or not prop.name:
                    # Some drivers (indi_pegasus_ppba 2.2) define empty placeholder vectors.
                    log.debug("ignoring property without device or name: %r", prop)
                    return
                self._devices.setdefault(prop.device, {})[prop.name] = prop
                self._emit(PropertyDefined(prop))
            case SetProperty():
                prop = self.get_property(message.device, message.name)
                if prop is None:
                    log.debug("update for undefined property %s.%s", message.device, message.name)
                    return
                changed = apply_set(prop, message)
                self._emit(PropertyUpdated(prop, tuple(changed)))
            case DeleteProperty(device=device, name=name):
                if name is None:
                    self._devices.pop(device, None)
                else:
                    self._devices.get(device, {}).pop(name, None)
                self._emit(PropertyDeleted(device, name))
            case Message(device=device, timestamp=timestamp, message=text):
                self._emit(MessageReceived(device, timestamp, text))
            case PingReply(uid=uid):
                if (answered := self._pings.get(uid)) is not None and not answered.done():
                    answered.set_result(None)

    def _emit(self, event: IndiEvent) -> None:
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                log.exception("INDI listener failed")
