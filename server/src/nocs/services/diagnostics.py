"""A zip of what a bug report needs: versions, the state and the services' logs.

The state holds no secrets (ADR 0014), but it does hold the site and the equipment:
the app says so before the owner shares the file.

``build`` blocks (it runs tools and compresses): call it from a thread.
"""

from __future__ import annotations

import io
import json
import platform
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from nocs import __version__
from nocs.state import Json

UNITS = ("nocsd", "nocs-indiserver", "nocs-phd2", "nocs-system")
PACKAGES = ("nocs", "indi-bin", "libindi1", "indi-3rdparty-drivers", "phd2")
JOURNAL_LINES = 20000
"""At most this many log lines, from the last 24 hours."""


def build(state: Json, hostname: str, now: datetime) -> tuple[str, bytes]:
    """The file name and the zip's bytes."""
    stamp = now.strftime("%Y%m%d-%H%M%S")
    name = f"nocs-diagnostics-{hostname}-{stamp}"
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{name}/versions.txt", versions())
        archive.writestr(f"{name}/state.json", json.dumps(state, indent=2) + "\n")
        archive.writestr(f"{name}/journal.txt", journal())
    return f"{name}.zip", data.getvalue()


def versions() -> str:
    lines = [
        f"nocs {__version__}",
        f"python {sys.version.split()[0]}",
        f"platform {platform.platform()}",
    ]
    model = Path("/proc/device-tree/model")
    if model.exists():
        lines.append(f"model {model.read_text(errors='replace').strip(chr(0))}")
    os_release = Path("/etc/os-release")
    if os_release.exists():
        lines += ["", os_release.read_text(errors="replace").strip()]
    lines += ["", _run("dpkg-query", "-W", "-f", "${Package} ${Version}\\n", *PACKAGES)]
    return "\n".join(lines) + "\n"


def journal() -> str:
    units = [arg for unit in UNITS for arg in ("-u", unit)]
    return _run(
        "journalctl", "--no-pager", "-o", "short-iso", "--since", "-24h",
        "-n", str(JOURNAL_LINES), *units,
    )  # fmt: skip


def _run(*argv: str) -> str:
    """What a tool printed, its errors included; a note when it cannot run."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError:
        return f"({argv[0]} is not installed)\n"
    except subprocess.TimeoutExpired:
        return f"({argv[0]} did not finish in 30 s)\n"
    return result.stdout + result.stderr
