"""A fake Raspberry Pi 5's device tree power node and USB sysfs, for nocs.equipment.usbpower."""

from pathlib import Path

from nocs.equipment.usbpower import UsbPaths


def pi(root: Path, *, enabled: int = 0, supply: int = 3000) -> UsbPaths:
    paths = UsbPaths(model=root / "compatible", power=root / "power", devices=root / "usb")
    paths.power.mkdir(parents=True)
    paths.model.write_bytes(b"raspberrypi,5-model-b\0brcm,bcm2712\0")
    paths.devices.mkdir(parents=True)
    (paths.power / "usb_max_current_enable").write_bytes(enabled.to_bytes(4, "big"))
    (paths.power / "max_current").write_bytes(supply.to_bytes(4, "big"))
    return paths


def device(
    paths: UsbPaths,
    name: str,
    *,
    product: str = "",
    vendor: str = "0000",
    attributes: str = "80",
    draw: int = 100,
    interfaces: tuple[str, ...] = ("ff",),
) -> None:
    """A USB device at ``name`` (``3-1``, ``5-1.4``); ``attributes`` e0 is a powered hub."""
    entry = paths.devices / name
    entry.mkdir()
    (entry / "product").write_text(f"{product}\n")
    (entry / "idVendor").write_text(f"{vendor}\n")
    (entry / "bmAttributes").write_text(f"{attributes}\n")
    (entry / "bMaxPower").write_text(f"{draw}mA\n")
    for i, cls in enumerate(interfaces):
        interface = paths.devices / f"{name}:1.{i}"
        interface.mkdir()
        (interface / "bInterfaceClass").write_text(f"{cls}\n")
        (entry / f"{name}:1.{i}").symlink_to(interface)
