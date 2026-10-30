"""Driver FIFO, driver catalog and serial ports."""

import os
from pathlib import Path

import pytest

from nocs.equipment import serial_ports
from nocs.indi.drivers import DriverControlError, DriverFifo, load_catalog


@pytest.fixture
def fifo(tmp_path: Path) -> Path:
    path = tmp_path / "fifo"
    os.mkfifo(path)
    return path


def test_fifo_commands(fifo: Path) -> None:
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        DriverFifo(fifo).start("indi_asi_ccd")
        DriverFifo(fifo).stop("indi_asi_ccd")
        assert os.read(reader, 1024) == b"start indi_asi_ccd\nstop indi_asi_ccd\n"
    finally:
        os.close(reader)


def test_fifo_without_indiserver_fails_fast(fifo: Path) -> None:
    with pytest.raises(DriverControlError, match="not reading"):
        DriverFifo(fifo).start("indi_asi_ccd")


def test_missing_fifo(tmp_path: Path) -> None:
    with pytest.raises(DriverControlError, match="cannot open"):
        DriverFifo(tmp_path / "nothing").start("indi_asi_ccd")


def test_fifo_rejects_unsafe_names(fifo: Path) -> None:
    with pytest.raises(ValueError, match="invalid driver"):
        DriverFifo(fifo).start("indi_x\nstop indi_y")


CATALOG = """<?xml version='1.0' encoding='utf-8'?>
<driversList>
    <devGroup group="Telescopes">
        <device label="ZWO AM5 USB" manufacturer="ZWO">
            <driver name="ZWO AM5">indi_lx200am5</driver>
            <version>1.5</version>
        </device>
        <device label="ZWO AM5 WiFi" manufacturer="ZWO">
            <driver name="ZWO AM5">indi_lx200am5</driver>
        </device>
        <device label="Broken"><driver name="x">rm -rf /</driver></device>
    </devGroup>
    <devGroup group="CCDs">
        <device label="ZWO CCD" manufacturer="ZWO">
            <driver name="ZWO CCD">indi_asi_ccd</driver>
        </device>
    </devGroup>
</driversList>
"""


def test_catalog(tmp_path: Path) -> None:
    (tmp_path / "drivers.xml").write_text(CATALOG)
    (tmp_path / "indi_asi.xml").write_text(CATALOG)  # duplicates collapse
    # Driver skeleton files live in the same directory.
    (tmp_path / "indi_tcfs_sk.xml").write_text("<INDIDriver><defSwitchVector/></INDIDriver>")
    (tmp_path / "garbage.xml").write_text("<driversList>")
    entries = load_catalog(tmp_path)
    assert [(e.group, e.label, e.driver) for e in entries] == [
        ("CCDs", "ZWO CCD", "indi_asi_ccd"),
        ("Telescopes", "ZWO AM5 USB", "indi_lx200am5"),
        ("Telescopes", "ZWO AM5 WiFi", "indi_lx200am5"),
    ]
    assert entries[1].name == "ZWO AM5"
    assert entries[1].manufacturer == "ZWO"


def test_catalog_missing_directory(tmp_path: Path) -> None:
    assert load_catalog(tmp_path / "none") == []


def test_serial_ports(tmp_path: Path) -> None:
    tty = tmp_path / "ttyACM0"
    tty.touch()
    (tmp_path / "by-id").mkdir()
    (tmp_path / "by-id" / "usb-ZWO_AM5-if00").symlink_to(tty)
    ports = serial_ports(tmp_path / "by-id")
    assert [(p.path.rsplit("/", 1)[1], p.device) for p in ports] == [("usb-ZWO_AM5-if00", str(tty))]
    assert serial_ports(tmp_path / "missing") == []
