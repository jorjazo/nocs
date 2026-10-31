"""Power boxes over INDI's standard power interface (INDI ≥ 2.1).

Outputs are identified as ``<kind>:<n>``, numbered from 1 in the order the
driver defines them (ADR 0017): ``dc`` (12 V outputs, ``POWER_CHANNELS``),
``dew`` (heaters, ``DEW_CHANNELS`` and ``DEW_DUTY_CYCLES``), ``usb``
(``USB_PORTS``) and ``variable``. The only variable output supported so far is
the Pegasus PPBA's adjustable one (``ADJOUT_VOLTAGE``, a choice of voltages);
the interface's own ``VARIABLE_CHANNELS`` are not used yet.

INDI 2.2.5's power interface matches the elements of a new vector by position,
not by name (fixed upstream later): a vector with only the channel that changes
would switch the first channel instead. Commands therefore always send every
element, in the driver's order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from nocs.devices.base import Device, DeviceError, DeviceInterface
from nocs.indi import Property
from nocs.indi.properties import NumberElement, SwitchElement, TextElement

ADJUSTABLE = "ADJOUT_VOLTAGE"
_ADJUSTABLE_VOLTS = re.compile(r"^ADJOUT_(\d+(?:\.\d+)?)V$")
DUTY_TOLERANCE = 1.0
"""Percent: drivers keep duty cycles as 0-255 (50 % reads back as 49.8 %)."""


class OutputKind(StrEnum):
    DC = "dc"
    DEW = "dew"
    USB = "usb"
    VARIABLE = "variable"


@dataclass(frozen=True, slots=True)
class _Channels:
    switches: str
    labels: str
    currents: str | None


_CHANNELS = {
    OutputKind.DC: _Channels("POWER_CHANNELS", "POWER_LABELS", "POWER_CURRENTS"),
    OutputKind.DEW: _Channels("DEW_CHANNELS", "DEW_LABELS", "DEW_CURRENTS"),
    OutputKind.USB: _Channels("USB_PORTS", "USB_LABELS", None),
}


@dataclass(frozen=True, slots=True)
class Output:
    id: str
    kind: OutputKind
    label: str
    on: bool
    current: float | None = None
    """Amperes, when the box measures this output."""
    duty: float | None = None
    """Dew heaters: power in percent."""
    voltage: float | None = None
    """Variable outputs: volts while on."""
    voltages: tuple[float, ...] = ()
    """Variable outputs: the voltages it can be set to."""


@dataclass(frozen=True, slots=True)
class PowerInput:
    voltage: float | None
    current: float | None
    power: float | None


def parse_output_id(output_id: str) -> tuple[OutputKind, int]:
    kind, _, number = output_id.partition(":")
    try:
        return OutputKind(kind), int(number)
    except ValueError:
        raise ValueError(f"invalid output {output_id!r}") from None


class PowerBox(Device):
    INTERFACE = DeviceInterface.POWER

    def not_ready(self) -> list[str]:
        if any(self.has(c.switches) for c in _CHANNELS.values()) or self.has("POWER_SENSORS"):
            return []
        return ["POWER_CHANNELS"]

    # -- reads ------------------------------------------------------------

    @property
    def outputs(self) -> list[Output]:
        outputs: list[Output] = []
        for kind, channels in _CHANNELS.items():
            if not self.has(channels.switches):
                continue
            switches = self.prop(channels.switches)
            for index, element in enumerate(switches.elements.values(), start=1):
                if not isinstance(element, SwitchElement):
                    continue
                outputs.append(
                    Output(
                        id=f"{kind.value}:{index}",
                        kind=kind,
                        label=self._label(channels.labels, element.name, element.label),
                        on=element.value,
                        current=self._number(channels.currents, element.name, index),
                        duty=self._number("DEW_DUTY_CYCLES", element.name, index)
                        if kind is OutputKind.DEW
                        else None,
                    )
                )
        if self.has(ADJUSTABLE):
            prop = self.prop(ADJUSTABLE)
            voltage = _adjustable_voltage(prop)
            outputs.append(
                Output(
                    id=f"{OutputKind.VARIABLE.value}:1",
                    kind=OutputKind.VARIABLE,
                    label=prop.label or "Adjustable",
                    on=voltage is not None,
                    voltage=voltage,
                    voltages=tuple(sorted(_adjustable_choices(prop).values())),
                )
            )
        return outputs

    def output(self, output_id: str) -> Output:
        for output in self.outputs:
            if output.id == output_id:
                return output
        raise ValueError(f"{self.name} has no output {output_id}")

    @property
    def input(self) -> PowerInput | None:
        if not self.has("POWER_SENSORS"):
            return None
        prop = self.prop("POWER_SENSORS")

        def read(name: str) -> float | None:
            element = prop.elements.get(name)
            return element.value if isinstance(element, NumberElement) else None

        return PowerInput(read("SENSOR_VOLTAGE"), read("SENSOR_CURRENT"), read("SENSOR_POWER"))

    @property
    def auto_dew(self) -> bool | None:
        """Whether the box drives its dew heaters itself; ``None`` if it cannot."""
        if not self.has("AUTO_DEW_CONTROL"):
            return None
        return any(
            e.value
            for e in self.prop("AUTO_DEW_CONTROL").elements.values()
            if isinstance(e, SwitchElement)
        )

    @property
    def auto_dew_aggression(self) -> float | None:
        """The PPBA's auto-dew aggressiveness in percent (read only: see the stage notes)."""
        if not self.has("AUTO_DEW_SETTINGS"):
            return None
        element = self.prop("AUTO_DEW_SETTINGS").elements.get("AGGRESSION")
        return element.value if isinstance(element, NumberElement) else None

    # -- commands ---------------------------------------------------------

    async def set_on(self, output_id: str, on: bool) -> None:
        """Switch a dc, dew or usb output."""
        kind, index = parse_output_id(output_id)
        if kind is OutputKind.VARIABLE:
            raise ValueError(f"{output_id} is switched by its voltage")
        name, values = self._vector(_CHANNELS[kind].switches, index, on)
        await self.command(_CHANNELS[kind].switches, values, done=lambda p: p.switch(name) is on)

    async def set_duty(self, output_id: str, duty: float) -> None:
        """Set a dew heater's power, 0-100 %."""
        kind, index = parse_output_id(output_id)
        if kind is not OutputKind.DEW:
            raise ValueError(f"{output_id} is not a dew heater")
        if not 0 <= duty <= 100:
            raise ValueError(f"duty cycle {duty:g} outside 0..100 %")
        name, values = self._vector("DEW_DUTY_CYCLES", index, duty)
        await self.command(
            "DEW_DUTY_CYCLES",
            values,
            done=lambda p: abs(p.number(name) - duty) <= DUTY_TOLERANCE,
        )

    async def set_voltage(self, output_id: str, voltage: float | None) -> None:
        """Set a variable output's voltage; ``None`` switches it off."""
        kind, index = parse_output_id(output_id)
        if kind is not OutputKind.VARIABLE or index != 1 or not self.has(ADJUSTABLE):
            raise ValueError(f"{self.name} has no variable output {output_id}")
        prop = self.prop(ADJUSTABLE)
        choices = _adjustable_choices(prop)
        if voltage is None:
            target = next((n for n in prop.elements if _ADJUSTABLE_VOLTS.match(n) is None), None)
        else:
            target = next((n for n, v in choices.items() if abs(v - voltage) < 0.05), None)
        if target is None:
            wanted = "off" if voltage is None else f"{voltage:g} V"
            raise ValueError(
                f"{output_id} cannot be set to {wanted} (has {sorted(choices.values())})"
            )
        await self.command(
            ADJUSTABLE,
            {name: name == target for name in prop.elements},
            done=lambda p: p.switch(target),
        )

    async def set_auto_dew(self, on: bool) -> None:
        if not self.has("AUTO_DEW_CONTROL"):
            raise DeviceError(f"{self.name} has no auto-dew")
        prop = self.prop("AUTO_DEW_CONTROL")
        await self.command(
            "AUTO_DEW_CONTROL",
            dict.fromkeys(prop.elements, on),
            done=lambda p: all(p.switch(n) is on for n in p.elements),
        )

    # -- internals --------------------------------------------------------

    def _vector[T: (bool, float)](
        self, name: str, index: int, value: T
    ) -> tuple[str, dict[str, str | float | bool]]:
        """Every element of ``name`` as it is, with the ``index``-th one set to ``value``."""
        prop = self.prop(name)
        elements = list(prop.elements.values())
        if not 1 <= index <= len(elements):
            raise ValueError(f"{self.name} has no {name} channel {index}")
        target = elements[index - 1].name
        values: dict[str, str | float | bool] = {}
        for element in elements:
            if element.name == target:
                values[element.name] = value
            elif isinstance(element, SwitchElement | NumberElement):
                values[element.name] = element.value
        return target, values

    def _label(self, labels: str, name: str, fallback: str) -> str:
        if self.has(labels):
            element = self.prop(labels).elements.get(name)
            if isinstance(element, TextElement) and element.value.strip():
                return element.value.strip()
        return fallback or name

    def _number(self, prop_name: str | None, name: str, index: int) -> float | None:
        """The element of ``prop_name`` for a channel: by name, else by position."""
        if prop_name is None or not self.has(prop_name):
            return None
        prop = self.prop(prop_name)
        element = prop.elements.get(name)
        if element is None:
            elements = list(prop.elements.values())
            element = elements[index - 1] if index <= len(elements) else None
        return element.value if isinstance(element, NumberElement) else None


def _adjustable_choices(prop: Property) -> dict[str, float]:
    return {
        name: float(match.group(1))
        for name in prop.elements
        if (match := _ADJUSTABLE_VOLTS.match(name)) is not None
    }


def _adjustable_voltage(prop: Property) -> float | None:
    choices = _adjustable_choices(prop)
    for name, element in prop.elements.items():
        if isinstance(element, SwitchElement) and element.value:
            return choices.get(name)
    return None
