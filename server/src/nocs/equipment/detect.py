"""Finding the serial port a device answers on, by trying them one by one (ADR 0048).

The driver is the test: given a port with its automatic search off, it connects when
its device is there (``Ok``) and fails otherwise (``Alert``). Some drivers never come
back from a port with another device on it (the ZWO AM5's, on a Pegasus power box's
port, waits forever for an answer): one that stops answering is restarted before the
next port. A device can still be answering what another driver asked it on its port
(the PPBA, after the AM5's handshake), and its own driver then reads that answer and
gives up: a refused connection is tried a second time.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence

from nocs.devices import Device, DeviceError, DeviceUnresponsive

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 20.0
"""Seconds a driver has to connect on a port; a handshake takes one or two."""
COMMAND_TIMEOUT = 10.0


class PortNotFoundError(DeviceError):
    """The device answered on none of the ports tried."""


SIMULATOR_PREFIX = "indi_simulator_"


def simulated(device: Device) -> bool:
    """Whether the device is one of INDI's simulators: some define a serial port (the
    telescope and focuser simulators' ``/dev/ttyUSB0``) that they never open."""
    if not device.has("DRIVER_INFO"):
        return False
    info = device.prop("DRIVER_INFO")
    return "DRIVER_EXEC" in info.elements and info.text("DRIVER_EXEC").startswith(SIMULATOR_PREFIX)


def uses_serial(device: Device) -> bool:
    """Whether the device connects through a serial port now (not over the network)."""
    if not device.has("DEVICE_PORT") or simulated(device):
        return False
    if device.has("CONNECTION_MODE"):
        mode = device.prop("CONNECTION_MODE")
        return "CONNECTION_SERIAL" not in mode.elements or mode.switch("CONNECTION_SERIAL")
    return True


async def no_auto_search(device: Device) -> None:
    """Turn the driver's own port search off: with it on, a driver that fails on its
    port goes on to try the others, and opens the ports of the rig's other devices."""
    if not device.has("DEVICE_AUTO_SEARCH"):
        return
    if not device.prop("DEVICE_AUTO_SEARCH").switch("INDI_ENABLED"):
        return
    try:
        await device.command(
            "DEVICE_AUTO_SEARCH",
            {"INDI_ENABLED": False, "INDI_DISABLED": True},
            timeout=COMMAND_TIMEOUT,
        )
    except DeviceError as e:
        log.warning("cannot turn %s's port search off: %s", device.name, e)


async def set_port(device: Device, port: str) -> None:
    """Point a serial device at ``port`` (it must not be connected)."""
    await no_auto_search(device)
    await device.command("DEVICE_PORT", {"PORT": port}, timeout=COMMAND_TIMEOUT)


async def connect(device: Device, timeout: float | None = None) -> None:
    """Connect a serial device on the port it is set to, a second time if it refuses.

    Raises ``DeviceUnresponsive`` when the driver stops answering, and ``DeviceError``
    when the device refuses twice."""
    for attempt in (1, 2):
        try:
            await device.command(
                "CONNECTION",
                {"CONNECT": True, "DISCONNECT": False},
                timeout=CONNECT_TIMEOUT if timeout is None else timeout,
                done=lambda p: p.switch("CONNECT"),
                # Drivers connect on their main thread, silent until they are done.
                watch_silence=False,
            )
            return
        except DeviceUnresponsive:
            raise
        except DeviceError as e:
            if attempt == 2:
                raise
            log.info("%s refused to connect, once: %s", device.name, e)


async def find_port(
    device: Device,
    ports: Sequence[str],
    *,
    restart: Callable[[], Awaitable[None]],
    progress: Callable[[str, int, int], None] = lambda port, attempt, attempts: None,
    timeout: float | None = None,
) -> str:
    """Try ``ports`` in order until the device connects on one; returns that port and
    leaves the device connected.

    ``restart`` restarts the driver when it stops answering; ``progress(port, attempt,
    attempts)`` is called before each try. Raises ``PortNotFoundError`` when no port
    works, and ``DeviceError`` when the driver cannot be restarted. ``timeout``
    defaults to ``CONNECT_TIMEOUT``.
    """
    for attempt, port in enumerate(ports, start=1):
        progress(port, attempt, len(ports))
        try:
            await set_port(device, port)
            await connect(device, timeout)
        except DeviceUnresponsive:
            log.info("%s stopped answering on %s: restarting its driver", device.name, port)
            await restart()
            continue
        except DeviceError as e:
            log.info("%s is not on %s: %s", device.name, port, e)
            continue
        log.info("%s answers on %s", device.name, port)
        return port
    if not ports:
        raise PortNotFoundError(f"no serial port to look for {device.name} on: is it plugged in?")
    raise PortNotFoundError(
        f"{device.name} answered on none of {len(ports)} serial ports: "
        "is it plugged in and switched on?"
    )
