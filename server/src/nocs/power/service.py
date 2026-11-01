"""Power outputs and dew heaters by role, and the environment readings (ADR 0017).

State under ``("power",)`` while the power role is ready, ``None`` otherwise::

    {device, outputs: [{id, kind, label, on, current, duty, voltage, voltages, feeds}],
     auto_dew, auto_dew_aggression, input: {voltage, current, power}}

and under ``("weather",)`` while the weather role is ready::

    {device, temperature, humidity, dew_point}

Labels and ``feeds`` come from the profile's power role. A dew heater that is
off shows the duty cycle it gets back when switched on. Cutting an output (off,
or a new voltage) is refused while a role it feeds is busy, or while any job
runs when the profile does not say what it feeds, unless forced. Commands to one
box run one at a time: each sends whole vectors built from the current values.

A device that stopped answering can be power cycled through the output that feeds
it (ADR 0030): off for a few seconds, back as it was, then its driver restarted.
Never the mount, which would lose its position.
"""

from __future__ import annotations

import asyncio
import logging

import anyio

from nocs.devices import (
    DeviceError,
    Output,
    OutputKind,
    PowerBox,
    WeatherSensor,
    parse_output_id,
)
from nocs.equipment import EquipmentService, OutputConfig, Role
from nocs.equipment.service import IndiConnection
from nocs.indi import IndiClient
from nocs.jobs import JobManager
from nocs.services.device_state import DeviceState
from nocs.state import Json, StateStore

log = logging.getLogger(__name__)

CYCLE_OFF = 5.0
"""Seconds an output stays off in a power cycle."""
CYCLE_SETTLE = 5.0
"""Seconds for a device to come up on USB after its power is back."""


class PowerNotReadyError(Exception):
    pass


class PowerCycleError(Exception):
    """A role cannot be power cycled."""


class AutoDewError(Exception):
    """A manual dew heater change while the box drives the heaters itself."""


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


class PowerService(DeviceState):
    ROLE = Role.POWER
    ROOT = ("power",)

    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        equipment: EquipmentService,
        bridge: IndiConnection,
    ) -> None:
        self._jobs = jobs
        self._lock = asyncio.Lock()
        self._duties: dict[tuple[str, str], float] = {}
        """Dew heaters switched off: the duty cycle to restore when they are switched on."""
        super().__init__(store, equipment, bridge)

    def box(self) -> PowerBox:
        if self._client is None or self._device is None:
            raise PowerNotReadyError("the power box is not connected")
        return PowerBox(self._client, self._device)

    async def set_output(
        self,
        output_id: str,
        *,
        on: bool | None = None,
        duty: float | None = None,
        voltage: float | None = None,
        force: bool = False,
        job: str | None = None,
    ) -> None:
        """Change one output; see ``OutputRequest`` for what each kind takes.

        Switching off an output that feeds a busy role is refused unless ``force``,
        or unless ``job`` (a sequence switching off its rig) is what holds it.
        """
        box = self.box()
        kind, _ = parse_output_id(output_id)
        output = box.output(output_id)
        async with self._lock:
            match kind:
                case OutputKind.DEW:
                    if on is None and duty is None:
                        raise ValueError("a dew heater takes on and/or duty")
                    if voltage is not None:
                        raise ValueError(f"{output_id} has no voltage")
                    if box.auto_dew:
                        raise AutoDewError("auto-dew drives the dew heaters: switch it off first")
                    await self._set_dew(box, output, on, duty)
                case OutputKind.VARIABLE:
                    if duty is not None:
                        raise ValueError(f"{output_id} has no duty cycle")
                    if voltage is not None and on is False:
                        raise ValueError("give a voltage to switch on, or on: false")
                    if voltage is None and on is not False:
                        raise ValueError(f"{output_id} takes a voltage, or on: false")
                    target = None if on is False else voltage
                    if target == output.voltage:
                        return
                    if output.on and not force:
                        self._check_feeds_free(output_id, job)
                    await box.set_voltage(output_id, target)
                case OutputKind.DC | OutputKind.USB:
                    if on is None or duty is not None or voltage is not None:
                        raise ValueError(f"{output_id} only takes on")
                    if output.on and not on and not force:
                        self._check_feeds_free(output_id, job)
                    await box.set_on(output_id, on)
        self.publish()

    def feeding(self, role: Role) -> str | None:
        """The output whose profile entry says it feeds ``role``."""
        for output_id, config in self._outputs_config().items():
            if role in config.feeds:
                return output_id
        return None

    async def power_cycle(
        self,
        role: Role,
        *,
        job: str | None = None,
        off: float = CYCLE_OFF,
        settle: float = CYCLE_SETTLE,
    ) -> None:
        """Switch off the output that feeds ``role``, back on as it was after ``off``
        seconds, and restart the role's driver (ADR 0030).

        Refused for the mount, for an output that also feeds the mount, and while
        another role the output feeds is in use (but by ``job``).
        """
        if role is Role.MOUNT:
            raise PowerCycleError("the mount is never power cycled: it would lose its position")
        output_id = self.feeding(role)
        if output_id is None:
            raise PowerCycleError(f"the profile names no output that feeds the {role.value}")
        if Role.MOUNT in self._outputs_config()[output_id].feeds:
            raise PowerCycleError(f"{output_id} also feeds the mount")
        box = self.box()
        kind, _ = parse_output_id(output_id)
        output = box.output(output_id)
        if kind is OutputKind.DEW:
            raise PowerCycleError(f"{output_id} is a dew heater")
        if not output.on:
            raise PowerCycleError(f"{output.label} is off")
        others = [r.value for r in self._outputs_config()[output_id].feeds if r is not role]
        self._jobs.check_free(r for r in others if job is None or self._jobs.holder(r) != job)
        log.warning("power cycling %s for the %s", output.label, role.value)
        async with self._lock:
            if kind is OutputKind.VARIABLE:
                await box.set_voltage(output_id, None)
            else:
                await box.set_on(output_id, False)
        self.publish()
        await anyio.sleep(off)
        async with self._lock:
            if kind is OutputKind.VARIABLE:
                await box.set_voltage(output_id, output.voltage)
            else:
                await box.set_on(output_id, True)
        self.publish()
        await anyio.sleep(settle)
        await self._equipment.restart_driver(role)

    async def set_auto_dew(self, on: bool) -> None:
        box = self.box()
        async with self._lock:
            await box.set_auto_dew(on)
        self.publish()

    # -- internals --------------------------------------------------------

    async def _set_dew(
        self, box: PowerBox, output: Output, on: bool | None, duty: float | None
    ) -> None:
        """Switch a dew heater and set its duty cycle, keeping the duty across off and on.

        Switched off, a PPBA channel reads back 0 % and would heat at 0 % when
        switched on again; a duty set while it is off would be overwritten by the
        driver's next reading. NOCS keeps the duty instead and applies it once the
        channel is on.
        """
        key = (box.name, output.id)
        if on is False or (on is None and not output.on):
            kept = duty if duty is not None else self._duties.get(key, output.duty)
            if kept:
                self._duties[key] = kept
            else:
                self._duties.pop(key, None)
            if output.on:
                await box.set_on(output.id, False)
            return
        if not output.on:
            await box.set_on(output.id, True)
            if duty is None:
                duty = self._duties.get(key)
        self._duties.pop(key, None)
        if duty is not None and duty != output.duty:
            await box.set_duty(output.id, duty)

    def _outputs_config(self) -> dict[str, OutputConfig]:
        profile = self._equipment.active_profile
        config = profile.devices.get(Role.POWER) if profile is not None else None
        return (config.outputs or {}) if config is not None else {}

    def _check_feeds_free(self, output_id: str, job: str | None = None) -> None:
        """Raise ``ResourceBusyError`` if what the output feeds is in use (but by ``job``)."""
        config = self._outputs_config().get(output_id)
        feeds = config.feeds if config is not None and config.feeds else list(Role)
        self._jobs.check_free(
            role.value for role in feeds if job is None or self._jobs.holder(role.value) != job
        )

    def summary(self, client: IndiClient, device: str) -> dict[str, Json]:
        box = PowerBox(client, device)
        config = self._outputs_config()
        power_input = box.input
        return {
            "device": device,
            "outputs": [
                _output(output, config.get(output.id), self._duties.get((device, output.id)))
                for output in box.outputs
            ],
            "auto_dew": box.auto_dew,
            "auto_dew_aggression": _round(box.auto_dew_aggression, 0),
            "input": None
            if power_input is None
            else {
                "voltage": _round(power_input.voltage, 2),
                "current": _round(power_input.current, 2),
                "power": _round(power_input.power, 1),
            },
        }


def _output(output: Output, config: OutputConfig | None, kept_duty: float | None) -> Json:
    """``kept_duty``: a dew heater that is off shows the duty it will get when switched on."""
    return {
        "id": output.id,
        "kind": output.kind.value,
        "label": config.label if config is not None and config.label else output.label,
        "on": output.on,
        "current": _round(output.current, 2),
        "duty": _round(kept_duty if kept_duty is not None and not output.on else output.duty, 0),
        "voltage": output.voltage,
        "voltages": list[Json](output.voltages),
        "feeds": [role.value for role in config.feeds] if config is not None else [],
    }


class WeatherService(DeviceState):
    ROLE = Role.WEATHER
    ROOT = ("weather",)

    def summary(self, client: IndiClient, device: str) -> dict[str, Json]:
        environment = WeatherSensor(client, device).environment
        return {
            "device": device,
            "temperature": _round(environment.temperature, 1),
            "humidity": _round(environment.humidity, 0),
            "dew_point": _round(environment.dew_point, 1),
        }


__all__ = [
    "AutoDewError",
    "DeviceError",
    "PowerNotReadyError",
    "PowerService",
    "WeatherService",
]
