"""Whether the Raspberry Pi's USB ports can power what hangs from them.

A Raspberry Pi 5 asks its supply over USB-PD for 5 A; one that does not offer it (the
Pi 4's 3 A supply, a cable or adapter in the way) leaves the Pi's four USB ports 600 mA
in all. A camera powered by them then drops out under load: the driver keeps
resetting it and sends no image. The firmware says so in the device tree
(``chosen/power``), and sysfs says what hangs from the ports, which hubs have power of
their own and what each device declares it draws. All of it is readable without
privileges.

Something is at risk when the ports are limited and a camera hangs from them on the
Pi's own power, or what the Pi powers declares more than the limit in all. Declared
draws are not peaks: a camera that declares 400 mA failed alone on a limited Pi.

``read_usb_power`` blocks (file system access): call it from a thread.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

LIMITED = 600
"""mA the Pi 5's USB ports give in all without a 5 A supply (1600 with one)."""

SELF_POWERED = 0x40
"""``bmAttributes`` bit of a device (a hub) with power of its own."""
VENDOR_SPECIFIC = "ff"
VIDEO = "0e"
CAMERA_VENDORS = frozenset(
    {
        "03c3",  # ZWO (its focusers and wheels are HID devices, its mounts serial)
        "1618",  # QHYCCD
        "a0a0",  # Player One
        "0547",  # ToupTek and the cameras built on it
        "f266",  # SVBONY
        "20e7",  # Atik
        "1278",  # Starlight Xpress
    }
)
"""USB vendors of astronomy cameras, which talk through a vendor-specific interface."""

_DEVICE = re.compile(r"^\d+-\d+(\.\d+)*$")
"""sysfs names of USB devices (``3-1``, ``5-1.4``); not root hubs or interfaces."""
_MILLIAMPS = re.compile(r"^(\d+)\s*mA$")


@dataclass(frozen=True, slots=True)
class UsbPaths:
    """Where the firmware and the kernel publish it (replaced in tests)."""

    power: Path = Path("/proc/device-tree/chosen/power")
    devices: Path = Path("/sys/bus/usb/devices")


@dataclass(frozen=True, slots=True)
class UsbPower:
    limit: int
    """mA the Pi's USB ports may give in all."""
    supply: int | None
    """mA the supply offered."""
    draw: int
    """mA declared by the devices the Pi powers."""
    cameras: tuple[str, ...]
    """Cameras the Pi powers, by their USB name."""


@dataclass(frozen=True, slots=True)
class _Device:
    name: str
    product: str
    vendor: str
    self_powered: bool
    draw: int
    interfaces: frozenset[str]


def read_usb_power(paths: UsbPaths, cameras: Collection[str] = ()) -> UsbPower | None:
    """What is at risk on the Pi's limited USB ports; ``None`` when they are not limited
    (or this is no Pi 5) or nothing is at risk. ``cameras`` are the INDI names of the
    profile's cameras: a USB device whose name is in one of them is a camera too."""
    enabled = _u32(paths.power / "usb_max_current_enable")
    if enabled is None or enabled != 0:
        return None
    devices = _devices(paths.devices)
    powered = [d for d in devices.values() if _on_pi_power(d, devices)]
    draw = sum(d.draw for d in powered)
    names = [name.casefold() for name in cameras]
    found = tuple(d.product or d.name for d in powered if _camera(d, names))
    if not found and draw <= LIMITED:
        return None
    return UsbPower(
        limit=LIMITED, supply=_u32(paths.power / "max_current"), draw=draw, cameras=found
    )


def _on_pi_power(device: _Device, devices: dict[str, _Device]) -> bool:
    """Neither the device nor a hub between it and the Pi has power of its own."""
    name: str | None = device.name
    while name is not None:
        current = devices.get(name)
        if current is None or current.self_powered:
            return False
        name = name.rpartition(".")[0] or None
    return True


def _camera(device: _Device, names: list[str]) -> bool:
    if VIDEO in device.interfaces:
        return True
    if device.vendor in CAMERA_VENDORS and VENDOR_SPECIFIC in device.interfaces:
        return True
    product = device.product.casefold()
    return len(product) >= 4 and any(product in name for name in names)


def _devices(root: Path) -> dict[str, _Device]:
    found: dict[str, _Device] = {}
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found
    for entry in entries:
        if not _DEVICE.match(entry.name):
            continue
        attributes = _text(entry / "bmAttributes")
        try:
            bits = int(attributes, 16) if attributes else 0
        except ValueError:
            bits = 0
        draw = _MILLIAMPS.match(_text(entry / "bMaxPower") or "")
        interfaces = frozenset(
            value
            for interface in entry.glob(f"{entry.name}:*")
            if (value := _text(interface / "bInterfaceClass"))
        )
        found[entry.name] = _Device(
            name=entry.name,
            product=_text(entry / "product") or "",
            vendor=(_text(entry / "idVendor") or "").lower(),
            self_powered=bool(bits & SELF_POWERED),
            draw=int(draw.group(1)) if draw else 0,
            interfaces=frozenset(i.lower() for i in interfaces),
        )
    return found


def _text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _u32(path: Path) -> int | None:
    """A device tree cell: a big-endian 32-bit integer."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return int.from_bytes(data[:4], "big") if len(data) >= 4 else None
