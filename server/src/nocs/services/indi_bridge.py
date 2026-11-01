"""Keeps a connection to indiserver and mirrors every device property into the state store.

A connected indiserver is pinged every ``PING_EVERY`` seconds: it answers itself,
whatever its drivers do. After ``MISSES`` unanswered pings it is taken as hung: the
bridge asks for it to be restarted (``on_hung``, nocs-system on the appliance) and
connects again (ADR 0030). A kernel keeps accepting connections for a frozen
process, so connecting alone proves nothing.

State layout under ``("indi",)``::

    server:  {host, port, connected, responsive, error}
    devices: {<device>: {interfaces: [...], properties: {<name>: <property>}}}
    messages: last driver messages (newest last)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping

from nocs.devices import DeviceInterface
from nocs.indi import (
    BlobElement,
    ConnectionLost,
    Element,
    IndiClient,
    IndiEvent,
    LightElement,
    MessageReceived,
    NumberElement,
    Property,
    PropertyDefined,
    PropertyDeleted,
    PropertyUpdated,
    SwitchElement,
    TextElement,
)
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("indi",)
_BACKOFF = (1.0, 2.0, 5.0, 10.0)
PING_EVERY = 10.0
PING_TIMEOUT = 10.0
MISSES = 3
"""Unanswered pings in a row after which indiserver is taken as hung (~1 min)."""
_MAX_MESSAGES = 50


def element_value(element: Element) -> Json:
    match element:
        case TextElement() | NumberElement() | SwitchElement():
            return element.value
        case LightElement():
            return element.value.value
        case BlobElement():
            return {"format": element.format, "size": element.size}


def element_to_json(element: Element) -> dict[str, Json]:
    data: dict[str, Json] = {"label": element.label, "value": element_value(element)}
    if isinstance(element, NumberElement):
        data |= {
            "format": element.format,
            "min": element.min,
            "max": element.max,
            "step": element.step,
        }
    return data


def property_to_json(prop: Property) -> dict[str, Json]:
    return {
        "type": prop.type.value,
        "label": prop.label,
        "group": prop.group,
        "state": prop.state.value,
        "perm": prop.perm.value,
        "rule": prop.rule.value if prop.rule else None,
        "timestamp": prop.timestamp,
        "message": prop.message,
        "elements": {name: element_to_json(el) for name, el in prop.elements.items()},
    }


def interface_names(prop: Property) -> list[Json]:
    """Lower-case names of the interfaces declared in a ``DRIVER_INFO`` property."""
    try:
        flags = DeviceInterface(int(prop.text("DRIVER_INTERFACE")))
    except (KeyError, TypeError, ValueError):
        return []
    return [flag.name.lower() for flag in DeviceInterface if flag and flag in flags and flag.name]


class NotConnectedError(Exception):
    pass


class IndiBridge:
    def __init__(
        self,
        store: StateStore,
        host: str,
        port: int,
        on_hung: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._store = store
        self._on_hung = on_hung
        self._host = host
        self._port = port
        self._client: IndiClient | None = None
        self._messages: list[Json] = []
        self._watchers: list[Callable[[IndiClient | None], None]] = []

    @property
    def client(self) -> IndiClient | None:
        return self._client if self._client is not None and self._client.connected else None

    def watch(self, watcher: Callable[[IndiClient | None], None]) -> Callable[[], None]:
        """Call ``watcher`` with each new connected client, and with ``None`` when it is lost."""
        self._watchers.append(watcher)
        return lambda: self._watchers.remove(watcher)

    async def run(self) -> None:
        """Connect and stay connected until cancelled, retrying with backoff."""
        attempt = 0
        self._publish_server(connected=False)
        while True:
            client = IndiClient(self._host, self._port)
            lost = asyncio.Event()

            def on_event(event: IndiEvent, lost: asyncio.Event = lost) -> None:
                self._mirror(event)
                if isinstance(event, ConnectionLost):
                    lost.set()

            client.add_listener(on_event)
            try:
                await client.connect()
            except (OSError, TimeoutError) as e:
                self._publish_server(connected=False, error=str(e) or type(e).__name__)
            else:
                attempt = 0
                # Devices were cleared when the previous connection ended; definitions
                # may already be arriving, so they must not be reset here.
                self._client = client
                self._publish_server(connected=True)
                log.info("connected to indiserver at %s:%s", self._host, self._port)
                self._notify(client)
                watch = asyncio.create_task(self._watch(client, lost), name="indi-ping")
                try:
                    await lost.wait()
                finally:
                    watch.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await watch
                    self._client = None
                    self._notify(None)
                    await client.close()
                log.warning("lost connection to indiserver")
            delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def _watch(self, client: IndiClient, lost: asyncio.Event) -> None:
        """Ping until the connection is lost; end it when indiserver stops answering."""
        misses = 0
        while True:
            await asyncio.sleep(PING_EVERY)
            try:
                await client.ping(PING_TIMEOUT)
            except TimeoutError:
                misses += 1
            except ConnectionError:
                return
            else:
                if misses:
                    log.info("indiserver answers again")
                    self._publish_server(connected=True)
                misses = 0
                continue
            silent = misses * (PING_EVERY + PING_TIMEOUT) - PING_EVERY
            log.warning("indiserver has not answered a ping for %.0f s", silent)
            if misses < MISSES:
                self._publish_server(
                    connected=True,
                    responsive=False,
                    error=f"indiserver has not answered for {silent:.0f} s",
                )
                continue
            log.error("indiserver is hung: restarting it")
            self._publish_server(connected=False, error="indiserver stopped answering")
            if self._on_hung is not None:
                try:
                    await self._on_hung()
                except Exception as e:  # reported; the bridge reconnects anyway
                    log.error("cannot restart indiserver: %s", e)
            lost.set()
            return

    async def set_property(
        self, device: str, name: str, values: Mapping[str, str | float | bool]
    ) -> None:
        client = self.client
        if client is None:
            raise NotConnectedError("not connected to indiserver")
        await client.send(device, name, values)

    def _notify(self, client: IndiClient | None) -> None:
        for watcher in list(self._watchers):
            try:
                watcher(client)
            except Exception:
                log.exception("indiserver connection watcher failed")

    def _publish_server(
        self, *, connected: bool, responsive: bool = True, error: str | None = None
    ) -> None:
        with self._store.transaction():
            self._store.set(
                (*ROOT, "server"),
                {
                    "host": self._host,
                    "port": self._port,
                    "connected": connected,
                    "responsive": connected and responsive,
                    "error": error,
                },
            )
            if not connected:
                self._store.set((*ROOT, "devices"), {})

    def _mirror(self, event: IndiEvent) -> None:
        devices = (*ROOT, "devices")
        match event:
            case PropertyDefined(property=prop):
                path = (*devices, prop.device, "properties", prop.name)
                with self._store.transaction():
                    self._store.set(path, property_to_json(prop))
                    if prop.name == "DRIVER_INFO":
                        self._store.set(
                            (*devices, prop.device, "interfaces"), interface_names(prop)
                        )
            case PropertyUpdated(property=prop, elements=changed):
                path = (*devices, prop.device, "properties", prop.name)
                with self._store.transaction():
                    self._store.set((*path, "state"), prop.state.value)
                    self._store.set((*path, "timestamp"), prop.timestamp)
                    self._store.set((*path, "message"), prop.message)
                    if prop.name == "DRIVER_INFO":
                        self._store.set(
                            (*devices, prop.device, "interfaces"), interface_names(prop)
                        )
                    for name in changed:
                        element = prop.elements[name]
                        if isinstance(element, NumberElement):
                            self._store.set((*path, "elements", name), element_to_json(element))
                        else:
                            value = element_value(element)
                            self._store.set((*path, "elements", name, "value"), value)
            case PropertyDeleted(device=device, name=name):
                if name is None:
                    self._store.delete((*devices, device))
                else:
                    self._store.delete((*devices, device, "properties", name))
            case MessageReceived(device=device, timestamp=timestamp, text=text):
                self._messages = [
                    *self._messages[-(_MAX_MESSAGES - 1) :],
                    {"device": device, "timestamp": timestamp, "text": text},
                ]
                self._store.set((*ROOT, "messages"), self._messages)
            case ConnectionLost():
                self._publish_server(connected=False, error=event.reason)
