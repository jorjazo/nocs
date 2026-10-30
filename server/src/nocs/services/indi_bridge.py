"""Keeps a connection to indiserver and mirrors every device property into the state store.

State layout under ``("indi",)``::

    server:  {host, port, connected, error}
    devices: {<device>: {interfaces: [...], properties: {<name>: <property>}}}
    messages: last driver messages (newest last)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

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
    def __init__(self, store: StateStore, host: str, port: int) -> None:
        self._store = store
        self._host = host
        self._port = port
        self._client: IndiClient | None = None
        self._messages: list[Json] = []

    @property
    def client(self) -> IndiClient | None:
        return self._client if self._client is not None and self._client.connected else None

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
                try:
                    await lost.wait()
                finally:
                    self._client = None
                    await client.close()
                log.warning("lost connection to indiserver")
            delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def set_property(
        self, device: str, name: str, values: Mapping[str, str | float | bool]
    ) -> None:
        client = self.client
        if client is None:
            raise NotConnectedError("not connected to indiserver")
        await client.send(device, name, values)

    def _publish_server(self, *, connected: bool, error: str | None = None) -> None:
        with self._store.transaction():
            self._store.set(
                (*ROOT, "server"),
                {"host": self._host, "port": self._port, "connected": connected, "error": error},
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
