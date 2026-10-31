"""The focuser role: its state and moves as jobs.

State under ``("focuser",)`` while the role is ready, ``None`` otherwise::

    {device, position, max_position, moving, target, temperature, can_abort}

A move (to a position, or by a number of steps) runs as a job that locks the
focuser; cancelling it, or ``abort``, stops the motor where it is.
"""

from __future__ import annotations

import asyncio
import logging

from nocs.devices import DeviceError, Focuser
from nocs.equipment import EquipmentService, Role
from nocs.equipment.service import IndiConnection
from nocs.indi import IndiClient, IndiEvent, PropertyDefined, PropertyUpdated
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("focuser",)
RESOURCE = Role.FOCUSER.value

_WATCHED = frozenset({"ABS_FOCUS_POSITION", "REL_FOCUS_POSITION", "FOCUS_MAX", "FOCUS_TEMPERATURE"})


class FocuserNotReadyError(Exception):
    pass


class FocuserService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        equipment: EquipmentService,
        bridge: IndiConnection,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._equipment = equipment
        self._client: IndiClient | None = bridge.client
        self._remove_listener = lambda: None
        self._device: str | None = None
        self._published: dict[str, Json] | None = None
        self._move: _Move | None = None

        store.set(ROOT, None)
        self._unwatch_bridge = bridge.watch(self._on_client)
        self._unwatch_equipment = equipment.add_listener(self._refresh)
        self._on_client(bridge.client)

    # -- commands ---------------------------------------------------------

    def focuser(self) -> Focuser:
        if self._client is None or self._device is None:
            raise FocuserNotReadyError("the focuser is not connected")
        return Focuser(self._client, self._device)

    def move_to(self, position: int) -> str:
        """Move to an absolute position; returns the job id."""
        focuser = self.focuser()
        focuser.check_position(position)
        self._jobs.check_free([RESOURCE])
        return self._start(focuser, position)

    def move_by(self, steps: int) -> str:
        """Move outward (positive) or inward (negative) by ``steps``; returns the job id."""
        if steps == 0:
            raise ValueError("a move needs a number of steps")
        focuser = self.focuser()
        target = focuser.position + steps
        focuser.check_position(target)
        self._jobs.check_free([RESOURCE])
        return self._start(focuser, target)

    async def abort(self) -> None:
        """Stop the focuser, whoever moved it."""
        job = self._jobs.job_holding(RESOURCE)
        if job is not None:
            self._jobs.cancel(job)  # the job aborts the move itself as well
        focuser = self.focuser()
        if not focuser.can_abort:
            raise DeviceError(f"{focuser.name} cannot abort a move")
        await focuser.abort()

    async def close(self) -> None:
        self._unwatch_bridge()
        self._unwatch_equipment()
        self._remove_listener()

    # -- internals ----------------------------------------------------------

    def _start(self, focuser: Focuser, target: int) -> str:
        async def run(context: JobContext) -> Json:
            self._move = _Move(context, focuser.position, target)
            context.progress(0.0, f"moving to {target}")
            self._publish()
            try:
                await focuser.move_to(target)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(focuser.abort())
                except (DeviceError, ConnectionError) as e:
                    log.error("%s: abort after cancelling failed: %s", focuser.name, e)
                raise
            finally:
                self._move = None
                self._publish()
            return {"position": focuser.position}

        return self._jobs.start("focus", [RESOURCE], run)

    def _on_client(self, client: IndiClient | None) -> None:
        self._remove_listener()
        self._remove_listener = lambda: None
        self._client = client
        if client is not None:
            self._remove_listener = client.add_listener(self._on_event)
        self._refresh()

    def _refresh(self) -> None:
        """Follow the focuser role as the equipment connects and disconnects."""
        name = self._equipment.ready_device(Role.FOCUSER) if self._client else None
        if name == self._device:
            return
        self._device = name
        self._published = None
        if name is None:
            self._store.set(ROOT, None)
            return
        self._publish()

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
            focuser = Focuser(self._client, self._device)
            summary = self._summary(focuser)
        except (DeviceError, KeyError, TypeError) as e:
            log.debug("focuser not publishable yet: %s", e)
            return
        if (move := self._move) is not None:
            move.report(focuser.position)
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

    def _summary(self, focuser: Focuser) -> dict[str, Json]:
        return {
            "device": focuser.name,
            "position": focuser.position,
            "max_position": focuser.max_position,
            "moving": focuser.moving or self._move is not None,
            "target": self._move.target if self._move is not None else None,
            "temperature": focuser.temperature,
            "can_abort": focuser.can_abort,
        }


class _Move:
    """A move in progress, to report how far it got."""

    def __init__(self, context: JobContext, start: int, target: int) -> None:
        self.context = context
        self.start = start
        self.target = target

    def report(self, position: int) -> None:
        distance = abs(self.target - self.start)
        if distance:
            self.context.progress(abs(position - self.start) / distance, f"moving to {self.target}")
