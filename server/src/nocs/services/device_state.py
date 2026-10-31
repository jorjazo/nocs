"""Publish the state of the device playing one role, as the equipment connects and changes.

A subclass names its role and state path and builds a summary from the device;
the base class follows the role, listens to the device's properties and writes
only the keys that changed, so a sensor ticking every second sends small
patches. The state is ``None`` while the role is not ready.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from nocs.devices import DeviceError
from nocs.equipment import EquipmentService, Role
from nocs.equipment.service import IndiConnection
from nocs.indi import IndiClient, IndiEvent, PropertyDefined, PropertyDeleted, PropertyUpdated
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)


class DeviceState:
    ROLE: ClassVar[Role]
    ROOT: ClassVar[Path]

    def __init__(self, store: StateStore, equipment: EquipmentService, bridge: IndiConnection):
        self._store = store
        self._equipment = equipment
        self._client: IndiClient | None = bridge.client
        self._remove_listener = lambda: None
        self._device: str | None = None
        self._published: dict[str, Json] | None = None

        store.set(self.ROOT, None)
        self._unwatch_bridge = bridge.watch(self._on_client)
        self._unwatch_equipment = equipment.add_listener(self._refresh)
        self._on_client(bridge.client)

    def close(self) -> None:
        self._unwatch_bridge()
        self._unwatch_equipment()
        self._remove_listener()

    def summary(self, client: IndiClient, device: str) -> dict[str, Json]:
        raise NotImplementedError

    def publish(self) -> None:
        if self._device is None or self._client is None:
            return
        try:
            summary = self.summary(self._client, self._device)
        except (DeviceError, KeyError, TypeError) as e:
            log.debug("%s not publishable yet: %s", self.ROLE.value, e)
            return
        previous = self._published
        if previous is None:
            self._store.set(self.ROOT, summary)
        else:
            changed = {k: v for k, v in summary.items() if previous.get(k) != v}
            if not changed:
                return
            with self._store.transaction():
                for key, value in changed.items():
                    self._store.set((*self.ROOT, key), value)
        self._published = summary

    def _on_client(self, client: IndiClient | None) -> None:
        self._remove_listener()
        self._remove_listener = lambda: None
        self._client = client
        if client is not None:
            self._remove_listener = client.add_listener(self._on_event)
        self._refresh()

    def _refresh(self) -> None:
        name = self._equipment.ready_device(self.ROLE) if self._client is not None else None
        if name == self._device:
            self.publish()  # the profile may have changed
            return
        self._device = name
        self._published = None
        if name is None:
            self._store.set(self.ROOT, None)
            return
        self.publish()

    def _on_event(self, event: IndiEvent) -> None:
        match event:
            case PropertyUpdated(property=prop) | PropertyDefined(property=prop) if (
                prop.device == self._device
            ):
                self.publish()
            case PropertyDeleted(device=device) if device == self._device:
                self.publish()
            case _:
                pass
