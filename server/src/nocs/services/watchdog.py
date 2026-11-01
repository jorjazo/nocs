"""systemd's watchdog for nocsd (ADR 0030).

Under ``Type=notify`` with ``WatchdogSec=``, nocsd says ``READY=1`` once it serves and
then ``WATCHDOG=1`` from a task on its event loop, three times per watchdog period:
an event loop stuck for the whole period gets nocsd killed and started again, which
then stops a mount it finds moving without a pad (ADR 0015). Outside systemd
(``NOTIFY_SOCKET`` unset) nothing happens.
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Mapping

import anyio

log = logging.getLogger(__name__)


def notify(message: str, environ: Mapping[str, str] = os.environ) -> bool:
    """Send one sd_notify message; whether there was a socket to send it to."""
    address = environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):  # abstract namespace
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as sock:
            sock.connect(address)
            sock.sendall(message.encode())
    except OSError as e:
        log.warning("cannot notify systemd: %s", e)
        return False
    return True


def interval(environ: Mapping[str, str] = os.environ) -> float | None:
    """Seconds between keep-alives, or ``None`` when systemd does not watch nocsd."""
    usec, pid = environ.get("WATCHDOG_USEC"), environ.get("WATCHDOG_PID")
    if not usec or (pid and pid != str(os.getpid())):
        return None
    return int(usec) / 1e6 / 3


async def run(environ: Mapping[str, str] = os.environ) -> None:
    """Say nocsd is ready, then keep the watchdog fed until cancelled."""
    notify("READY=1", environ)
    every = interval(environ)
    if every is None:
        return
    log.info("feeding systemd's watchdog every %.0f s", every)
    while True:
        notify("WATCHDOG=1", environ)
        await anyio.sleep(every)
