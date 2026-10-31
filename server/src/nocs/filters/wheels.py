"""Filter names per physical wheel, apart from profiles (ADR 0016).

``<config dir>/filter-wheels.json`` maps a wheel's key to its label and one name
per slot. The key is ``serial:<number>`` when the driver publishes a serial
number, else ``device:<INDI device name>``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nocs.equipment.profiles import write_atomic

log = logging.getLogger(__name__)

FILE_NAME = "filter-wheels.json"
MAX_NAME = 32


class WheelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="", max_length=80)
    filters: list[str] = Field(description="One name per slot, in order; empty = no filter.")
    confirmed: bool = Field(
        default=False, description="The user said what sits in each slot (not only the driver)."
    )

    @field_validator("filters")
    @classmethod
    def _check_names(cls, filters: list[str]) -> list[str]:
        return check_names(filters)


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wheels: dict[str, WheelConfig] = Field(default_factory=dict[str, WheelConfig])


def check_names(filters: list[str]) -> list[str]:
    """Trimmed names; two slots may not share one (except empty slots)."""
    names = [name.strip() for name in filters]
    seen: set[str] = set()
    for name in names:
        if len(name) > MAX_NAME:
            raise ValueError(f"filter name {name!r} is longer than {MAX_NAME} characters")
        key = name.casefold()
        if key and key in seen:
            raise ValueError(f"two slots are named {name!r}")
        seen.add(key)
    return names


def wheel_key(serial_number: str | None, device: str) -> str:
    return f"serial:{serial_number}" if serial_number else f"device:{device}"


class WheelStore:
    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / FILE_NAME

    def load(self) -> dict[str, WheelConfig]:
        try:
            return _File.model_validate_json(self._path.read_bytes()).wheels
        except FileNotFoundError:
            return {}
        except (OSError, ValidationError) as e:
            log.warning("ignoring unreadable %s: %s", self._path, e)
            return {}

    def get(self, key: str) -> WheelConfig | None:
        return self.load().get(key)

    def put(self, key: str, wheel: WheelConfig) -> None:
        wheels = self.load()
        wheels[key] = wheel
        write_atomic(self._path, _File(wheels=wheels).model_dump_json(indent=2) + "\n")
