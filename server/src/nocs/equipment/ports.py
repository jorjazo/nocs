"""Serial ports for devices configured through ``DEVICE_PORT`` (mounts, power boxes)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BY_ID = Path("/dev/serial/by-id")


@dataclass(frozen=True, slots=True)
class SerialPort:
    path: str
    """Stable name, e.g. ``/dev/serial/by-id/usb-Pegasus_Astro_PPBA...-if00``."""
    device: str
    """What it points to now, e.g. ``/dev/ttyUSB0`` (changes with plugging order)."""


def serial_ports(by_id: Path = BY_ID) -> list[SerialPort]:
    """USB serial adapters by their stable udev names (empty if there are none)."""
    if not by_id.is_dir():
        return []
    return [
        SerialPort(path=str(link), device=str(link.resolve()))
        for link in sorted(by_id.iterdir())
        if link.is_symlink()
    ]
