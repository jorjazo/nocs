"""Serial ports for devices configured through ``DEVICE_PORT`` (mounts, power boxes).

Finding a device's port (ADR 0048) tries the ports one by one; these helpers decide
which ones and in what order: the ones whose stable name looks like the device first.
"""

from __future__ import annotations

import os
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

BY_ID = Path("/dev/serial/by-id")
GPS_WORDS = ("gps", "gnss")
"""In the stable name of a USB GPS (``usb-u-blox_AG_..._GPS_GNSS_Receiver-if00``): gpsd's."""
COMMON_WORDS = frozenset(
    {"indi", "usb", "serial", "device", "port", "driver", "generic", "simulator", "telescope"}
)
"""Words of driver and device names that say nothing about who made the device."""


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


def real_path(port: str) -> str:
    """The device node a port name stands for (a by-id link resolved)."""
    return os.path.realpath(port)


def stable_name(port: str, ports: Iterable[SerialPort]) -> str:
    """The by-id name of ``port`` when it has one, else ``port`` itself."""
    node = real_path(port)
    return next((p.path for p in ports if p.device == node), port)


def words(*names: str | None) -> frozenset[str]:
    """What a device's names say about it, to match against a port's stable name:
    ``ZWO AM5`` gives ``zwo`` and ``am5``, ``indi_pegasus_ppba`` ``pegasus`` and ``ppba``."""
    found: set[str] = set()
    for name in names:
        for word in re.findall(r"[a-z0-9]+", (name or "").lower()):
            if len(word) >= 3 and word not in COMMON_WORDS:
                found.add(word)
    return frozenset(found)


def affinity(port: SerialPort, device_words: Collection[str]) -> int:
    """How many of a device's words begin a word of the port's stable name (``ppba``:
    ``PPBADV``)."""
    tokens = re.findall(r"[a-z0-9]+", Path(port.path).name.lower())
    return sum(1 for word in device_words if any(token.startswith(word) for token in tokens))


def looks_like_gps(port: SerialPort) -> bool:
    name = Path(port.path).name.lower()
    return any(word in name for word in GPS_WORDS)


def ranked(
    ports: Sequence[SerialPort],
    own: Collection[str],
    others: Sequence[Collection[str]] = (),
    *,
    exclude: Collection[str] = (),
) -> list[SerialPort]:
    """The ports worth trying for a device, the likeliest first.

    Ports whose stable name matches the device's words come first, the best match
    leading; ports that match another device of the rig better than this one go last.
    ``exclude`` holds ports taken by other devices or by gpsd (any name of theirs); GPS
    receivers are left out too.
    """
    taken = {real_path(port) for port in exclude} | set(exclude)

    def key(item: tuple[int, SerialPort]) -> tuple[int, int, int]:
        index, port = item
        mine = affinity(port, own)
        theirs = max((affinity(port, other) for other in others), default=0)
        group = 0 if mine > theirs else 2 if theirs > mine else 1
        return group, -mine, index

    usable = [
        (index, port)
        for index, port in enumerate(ports)
        if port.path not in taken and port.device not in taken and not looks_like_gps(port)
    ]
    return [port for _, port in sorted(usable, key=key)]
