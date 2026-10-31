"""The filter wheel role: its state, filter changes as jobs, and its filter names.

State under ``("filter_wheel",)`` while the role is ready, ``None`` otherwise::

    {device, key, label, slot, filter, names, slots, moving, confirmed}

Names are kept per physical wheel (``nocs.filters.wheels``, ADR 0016): when a
wheel becomes ready NOCS sends its driver the names it knows for that wheel. A
wheel it has not seen keeps its driver's names and stays unconfirmed until the
user says what sits in each slot.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Coroutine
from typing import Any

from nocs.devices import DeviceError, FilterWheel
from nocs.devices.base import SERIAL_PROPERTIES
from nocs.equipment import EquipmentService, Role
from nocs.equipment.service import IndiConnection
from nocs.filters.wheels import WheelConfig, WheelStore, check_names, wheel_key
from nocs.indi import IndiClient, IndiEvent, PropertyDefined, PropertyUpdated
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("filter_wheel",)
RESOURCE = Role.FILTER_WHEEL.value
SERIAL_WAIT = 1.0
"""How long to wait for a serial number after the wheel is ready (drivers define it last)."""

_WATCHED = frozenset({"FILTER_SLOT", "FILTER_NAME", *SERIAL_PROPERTIES})


class FilterWheelNotReadyError(Exception):
    pass


class FilterWheelService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        equipment: EquipmentService,
        bridge: IndiConnection,
        wheels: WheelStore,
        *,
        serial_wait: float = SERIAL_WAIT,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._equipment = equipment
        self._wheels = wheels
        self._serial_wait = serial_wait
        self._client: IndiClient | None = bridge.client
        self._remove_listener = lambda: None
        self._device: str | None = None
        self._key: str | None = None
        """The physical wheel, once identified; ``None`` right after it becomes ready."""
        self._config: WheelConfig | None = None
        self._published: dict[str, Json] | None = None
        self._tasks: set[asyncio.Task[object]] = set()

        store.set(ROOT, None)
        self._unwatch_bridge = bridge.watch(self._on_client)
        self._unwatch_equipment = equipment.add_listener(self._refresh)
        self._on_client(bridge.client)

    # -- commands ---------------------------------------------------------

    def wheel(self) -> FilterWheel:
        if self._client is None or self._device is None:
            raise FilterWheelNotReadyError("the filter wheel is not connected")
        return FilterWheel(self._client, self._device)

    def select(self, filter: int | str) -> str:
        """Move to a slot (1-based) or to the named filter; returns the job id."""
        self._slot(filter)  # refused now, not in the job
        self._jobs.check_free([RESOURCE])

        async def run(context: JobContext) -> Json:
            return await self.select_in(context, filter)

        return self._jobs.start("filter", [RESOURCE], run)

    async def select_in(self, context: JobContext, filter: int | str) -> Json:
        """Move to a slot or a named filter inside ``context``'s job, which holds the wheel."""
        if self._jobs.holder(RESOURCE) != context.id:
            raise RuntimeError(f"job {context.id} does not hold the filter wheel")
        wheel, slot, name = self._slot(filter)
        context.progress(None, f"changing to {name or f'slot {slot}'}")
        await wheel.select(slot)
        return {"slot": slot, "filter": name or None}

    def _slot(self, filter: int | str) -> tuple[FilterWheel, int, str]:
        wheel = self.wheel()
        slot = wheel.slot_of(filter) if isinstance(filter, str) else filter
        if not 1 <= slot <= wheel.slots:
            raise ValueError(f"slot {slot} outside 1..{wheel.slots}")
        names = wheel.names
        return wheel, slot, names[slot - 1].strip() if slot <= len(names) else ""

    async def set_names(self, filters: list[str], label: str | None = None) -> None:
        """Say what sits in each slot of the wheel connected now; sent to its driver too."""
        self._jobs.check_free([RESOURCE])
        wheel = self.wheel()
        if self._key is None:
            raise FilterWheelNotReadyError(f"{wheel.name} is still being identified")
        filters = check_names(filters)
        if len(filters) != wheel.slots:
            raise ValueError(f"{wheel.name} has {wheel.slots} slots, got {len(filters)} names")
        previous = self._config
        config = WheelConfig(
            label=label if label is not None else (previous.label if previous else ""),
            filters=filters,
            confirmed=True,
        )
        self._wheels.put(self._key, config)
        self._config = config
        if wheel.names != filters:
            await wheel.set_names(filters)
        self._publish()

    async def close(self) -> None:
        self._unwatch_bridge()
        self._unwatch_equipment()
        self._remove_listener()
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.wait(self._tasks)

    # -- internals ----------------------------------------------------------

    def _on_client(self, client: IndiClient | None) -> None:
        self._remove_listener()
        self._remove_listener = lambda: None
        self._client = client
        if client is not None:
            self._remove_listener = client.add_listener(self._on_event)
        self._refresh()

    def _refresh(self) -> None:
        """Follow the filter wheel role as the equipment connects and disconnects."""
        name = self._equipment.ready_device(Role.FILTER_WHEEL) if self._client else None
        if name == self._device:
            return
        self._device = name
        self._key = None
        self._config = None
        self._published = None
        if name is None:
            self._store.set(ROOT, None)
            return
        self._publish()
        self._background(self._identify(name))

    async def _identify(self, device: str) -> None:
        """Find out which wheel this is and give its driver the names NOCS has for it."""
        client = self._client
        assert client is not None
        wheel = FilterWheel(client, device)
        # A driver without serial numbers: the wheel is known by its device name.
        with contextlib.suppress(TimeoutError):
            await client.wait_for(lambda _: wheel.serial_number is not None, self._serial_wait)
        if self._device != device:
            return
        key = wheel_key(wheel.serial_number, device)
        config = self._wheels.get(key)
        names = wheel.names
        if config is not None and len(config.filters) != len(names):
            log.warning(
                "%s (%s) has %d slots but NOCS knew it with %d: its names must be set again",
                device,
                key,
                len(names),
                len(config.filters),
            )
            config = None
        if config is None:
            config = WheelConfig(label="", filters=check_names(names), confirmed=False)
            try:
                self._wheels.put(key, config)
            except (OSError, ValueError) as e:
                log.warning("cannot record filter wheel %s: %s", key, e)
        self._key, self._config = key, config
        self._publish()
        if config.filters != names:
            try:
                await wheel.set_names(config.filters)
            except (DeviceError, ConnectionError, ValueError) as e:
                log.warning("cannot name the filters of %s: %s", device, e)

    def _on_event(self, event: IndiEvent) -> None:
        match event:
            case PropertyUpdated(property=prop) | PropertyDefined(property=prop) if (
                prop.device == self._device and prop.name in _WATCHED
            ):
                self._publish()
            case _:
                pass

    def _publish(self) -> None:
        if self._device is None or self._client is None:
            return
        try:
            summary = self._summary(FilterWheel(self._client, self._device))
        except (DeviceError, KeyError, TypeError) as e:
            log.debug("filter wheel not publishable yet: %s", e)
            return
        previous = self._published
        if previous is None:
            self._store.set(ROOT, summary)
        else:
            changed = {k: v for k, v in summary.items() if previous.get(k) != v}
            if not changed:
                return
            with self._store.transaction():
                for key, value in changed.items():
                    self._store.set((*ROOT, key), value)
        self._published = summary

    def _summary(self, wheel: FilterWheel) -> dict[str, Json]:
        config = self._config
        slot = wheel.slot
        return {
            "device": wheel.name,
            "key": self._key,
            "label": config.label if config else "",
            "slot": slot if slot > 0 else None,
            "filter": wheel.filter,
            "names": list[Json](name.strip() for name in wheel.names),
            "slots": wheel.slots,
            "moving": wheel.moving,
            "confirmed": config.confirmed if config else False,
        }

    def _background(self, coro: Coroutine[Any, Any, object]) -> None:
        task: asyncio.Task[object] = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
