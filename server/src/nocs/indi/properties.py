"""INDI property model: vectors of typed elements, as defined by the INDI protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PropertyType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    SWITCH = "switch"
    LIGHT = "light"
    BLOB = "blob"


class PropertyState(StrEnum):
    IDLE = "Idle"
    OK = "Ok"
    BUSY = "Busy"
    ALERT = "Alert"


class Permission(StrEnum):
    READ_ONLY = "ro"
    WRITE_ONLY = "wo"
    READ_WRITE = "rw"


class SwitchRule(StrEnum):
    ONE_OF_MANY = "OneOfMany"
    AT_MOST_ONE = "AtMostOne"
    ANY_OF_MANY = "AnyOfMany"


@dataclass(slots=True)
class TextElement:
    name: str
    label: str
    value: str = ""


@dataclass(slots=True)
class NumberElement:
    name: str
    label: str
    value: float = 0.0
    format: str = "%g"
    min: float = 0.0
    max: float = 0.0
    step: float = 0.0


@dataclass(slots=True)
class SwitchElement:
    name: str
    label: str
    value: bool = False


@dataclass(slots=True)
class LightElement:
    name: str
    label: str
    value: PropertyState = PropertyState.IDLE


@dataclass(slots=True)
class BlobElement:
    name: str
    label: str
    format: str = ""
    size: int = 0
    data: bytes | None = None


type Element = TextElement | NumberElement | SwitchElement | LightElement | BlobElement


@dataclass(slots=True)
class Property:
    device: str
    name: str
    type: PropertyType
    label: str = ""
    group: str = ""
    state: PropertyState = PropertyState.IDLE
    perm: Permission = Permission.READ_ONLY
    rule: SwitchRule | None = None
    timeout: float = 0.0
    timestamp: str | None = None
    message: str | None = None
    elements: dict[str, Element] = field(default_factory=lambda: {})

    @property
    def key(self) -> tuple[str, str]:
        return (self.device, self.name)

    def switch(self, name: str) -> bool:
        element = self.elements[name]
        if not isinstance(element, SwitchElement):
            raise TypeError(f"{self.device}.{self.name}.{name} is not a switch")
        return element.value

    def number(self, name: str) -> float:
        element = self.elements[name]
        if not isinstance(element, NumberElement):
            raise TypeError(f"{self.device}.{self.name}.{name} is not a number")
        return element.value

    def text(self, name: str) -> str:
        element = self.elements[name]
        if not isinstance(element, TextElement):
            raise TypeError(f"{self.device}.{self.name}.{name} is not a text")
        return element.value
