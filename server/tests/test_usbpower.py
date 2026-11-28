"""Whether the Raspberry Pi's limited USB ports power something at risk."""

from pathlib import Path

from usbtree import device, pi

from nocs.equipment.usbpower import UsbPaths, UsbPower, read_usb_power


def rig(paths: UsbPaths, *, camera_at: str) -> None:
    """willy's: a mount on the Pi, a power box's powered hub with a focuser behind a
    bus-powered hub, and the camera at ``camera_at``."""
    device(
        paths, "4-2", product="ZWO Device", vendor="03c3", attributes="a0", interfaces=("02", "0a")
    )
    device(paths, "4-1", product="USB2.0 Hub", attributes="e0", draw=0, interfaces=("09",))
    device(paths, "5-1", product="USB3.0 Hub", attributes="e0", draw=0, interfaces=("09",))
    device(paths, "4-1.2", attributes="e0", draw=2, interfaces=("09",))
    device(paths, "4-1.2.1", product="ZWO EFF", vendor="03c3", draw=64, interfaces=("03",))
    device(paths, "5-1.3", product="SanDisk 3.2Gen1", draw=896, interfaces=("08",))
    device(paths, camera_at, product="ASI432MM", vendor="03c3", draw=400)


def test_a_camera_on_the_pis_limited_ports(tmp_path: Path) -> None:
    paths = pi(tmp_path)
    rig(paths, camera_at="3-1")
    assert read_usb_power(paths) == UsbPower(
        limit=600, supply=3000, draw=500, cameras=("ASI432MM",)
    )


def test_a_camera_behind_a_powered_hub_is_safe(tmp_path: Path) -> None:
    paths = pi(tmp_path)
    rig(paths, camera_at="5-1.4")
    assert read_usb_power(paths) is None


def test_a_bus_powered_hub_does_not_power_the_camera(tmp_path: Path) -> None:
    paths = pi(tmp_path)
    device(paths, "3-1", product="Hub", attributes="a0", draw=100, interfaces=("09",))
    device(paths, "3-1.2", product="ASI120MM Mini", vendor="03c3", draw=300)
    found = read_usb_power(paths)
    assert found is not None
    assert (found.draw, found.cameras) == (400, ("ASI120MM Mini",))


def test_too_much_declared_without_a_camera(tmp_path: Path) -> None:
    paths = pi(tmp_path)
    device(paths, "3-1", product="SSD", draw=896, interfaces=("08",))
    assert read_usb_power(paths) == UsbPower(limit=600, supply=3000, draw=896, cameras=())
    (paths.devices / "3-1" / "bMaxPower").write_text("500mA\n")
    assert read_usb_power(paths) is None


def test_cameras_by_video_class_or_their_indi_name(tmp_path: Path) -> None:
    paths = pi(tmp_path)
    device(paths, "1-1", product="Webcam", draw=100, interfaces=("0e", "01"))
    device(paths, "2-1", product="Mars-C", vendor="1234", draw=100)
    device(paths, "3-1", product="Thing", vendor="1234", draw=100)
    found = read_usb_power(paths, cameras=["PlayerOne CCD Mars-C"])
    assert found is not None
    assert found.cameras == ("Webcam", "Mars-C")


def test_nothing_when_the_ports_are_not_limited(tmp_path: Path) -> None:
    paths = pi(tmp_path, enabled=1, supply=5000)
    rig(paths, camera_at="3-1")
    assert read_usb_power(paths) is None


def test_nothing_on_a_computer_that_is_no_pi_5(tmp_path: Path) -> None:
    none = tmp_path / "none"
    assert read_usb_power(UsbPaths(model=none, power=none, devices=none)) is None
    paths = pi(tmp_path / "pi4")
    paths.model.write_bytes(b"raspberrypi,4-model-b\0brcm,bcm2711\0")
    rig(paths, camera_at="3-1")
    assert read_usb_power(paths) is None
