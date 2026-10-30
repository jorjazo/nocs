"""Driver lifecycle through indiserver's FIFO, and the catalog of installed drivers.

indiserver started with ``-f <fifo>`` reads one command per line from the FIFO:
``start <driver>`` and ``stop <driver>``. It does not answer: whether a driver
came up is seen on the protocol connection, when its devices are defined.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DRIVER_NAME = re.compile(r"^[A-Za-z0-9_.+-]{1,128}$")


class DriverControlError(Exception):
    """A driver command could not be delivered to indiserver."""


class DriverFifo:
    def __init__(self, path: Path) -> None:
        self.path = path

    def start(self, driver: str) -> None:
        self._command("start", driver)

    def stop(self, driver: str) -> None:
        self._command("stop", driver)

    def _command(self, verb: str, driver: str) -> None:
        if not DRIVER_NAME.fullmatch(driver):
            raise ValueError(f"invalid driver name {driver!r}")
        line = f"{verb} {driver}\n".encode()
        # Non-blocking: opening a FIFO nobody reads fails at once (ENXIO) instead of
        # hanging, and a line this short is written atomically.
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            if e.errno == errno.ENXIO:
                raise DriverControlError(f"indiserver is not reading {self.path}") from e
            raise DriverControlError(f"cannot open driver FIFO {self.path}: {e}") from e
        try:
            os.write(fd, line)
        except OSError as e:
            raise DriverControlError(f"cannot write to driver FIFO {self.path}: {e}") from e
        finally:
            os.close(fd)
        log.info("indiserver: %s %s", verb, driver)


@dataclass(frozen=True, slots=True)
class DriverInfo:
    driver: str
    """Executable, e.g. ``indi_asi_ccd``."""
    name: str
    """Driver name, e.g. ``ZWO CCD``."""
    label: str
    """Device model the entry is for, e.g. ``ZWO AM5 USB`` (one driver, many models)."""
    manufacturer: str
    group: str
    """Catalog group, e.g. ``CCDs`` or ``Telescopes``."""


def load_catalog(directory: Path) -> list[DriverInfo]:
    """Read every INDI driver catalog file (``drivers.xml`` and third-party ones)."""
    entries: set[DriverInfo] = set()
    for path in sorted(directory.glob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as e:
            log.debug("skipping %s: %s", path, e)
            continue
        # Driver skeleton files share the directory; only catalogs have this root.
        if root.tag != "driversList":
            continue
        for group in root.iter("devGroup"):
            for device in group.iter("device"):
                driver = device.find("driver")
                executable = (driver.text or "").strip() if driver is not None else ""
                if driver is None or not DRIVER_NAME.fullmatch(executable):
                    continue
                entries.add(
                    DriverInfo(
                        driver=executable,
                        name=driver.get("name", executable),
                        label=device.get("label", executable),
                        manufacturer=device.get("manufacturer", ""),
                        group=group.get("group", ""),
                    )
                )
    return sorted(entries, key=lambda e: (e.group, e.manufacturer, e.label, e.driver))
