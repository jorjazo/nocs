"""nocsd stops cleanly on SIGTERM, as systemd stops it."""

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sigterm_ends_nocsd_normally(tmp_path: Path) -> None:
    """uvicorn raises SIGTERM again after its shutdown; under Python's own handler that
    killed nocsd before its log thread wrote the last records and before multiprocessing
    unlinked the imaging worker's semaphores (sem_unlink tracebacks on the lab Pi)."""
    env = {
        **os.environ,
        "NOCS_PORT": str(free_port()),
        "NOCS_INDI_PORT": str(free_port()),  # nothing there: the bridge keeps retrying
        "NOCS_PHD2_PORT": str(free_port()),
        "NOCS_GPSD_PORT": str(free_port()),
        "NOCS_CONFIG_DIR": str(tmp_path / "config"),
        "NOCS_DATA_DIR": str(tmp_path / "data"),
        "NOCS_SYSTEM_SOCKET": str(tmp_path / "no-socket"),
    }
    nocsd = subprocess.Popen(
        [sys.executable, "-m", "nocs"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    lines: list[str] = []
    running = threading.Event()

    def read() -> None:
        assert nocsd.stderr is not None
        for line in nocsd.stderr:
            lines.append(line)
            if "Uvicorn running on" in line:
                running.set()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        assert running.wait(60), "".join(lines)
        time.sleep(1)  # the imaging worker starts with the app
        nocsd.send_signal(signal.SIGTERM)
        assert nocsd.wait(30) == 0, "".join(lines)
    finally:
        if nocsd.poll() is None:
            nocsd.kill()
    reader.join(10)
    log = "".join(lines)
    assert "Application shutdown complete." in log
    assert "Finished server process" in log
    assert "Traceback" not in log
    assert "leaked" not in log
