"""A stand-in for ASTAP's command-line solver, and frames for it (they are only headers)."""

import stat
import sys
from pathlib import Path
from typing import Any

import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]

from nocs.solving import Astap

_fits: Any = fits

# ASTAP's result for one of the maintainer's frames of M 8: ZWO ASI2600MC Duo at 384 mm,
# 6248 x 4176 px, rows top-down, camera angle 316° according to ASIAIR.
M8 = {
    "PLTSOLVD": "T",
    "CRPIX1": "3.1245000000000000E+003",
    "CRPIX2": "2.0885000000000000E+003",
    "CRVAL1": "2.7092749705717387E+002",
    "CRVAL2": "-2.3762873522508709E+001",
    "CD1_1": "-4.0649848345283222E-004",
    "CD1_2": "-3.8515240898436026E-004",
    "CD2_1": "3.8514657177160457E-004",
    "CD2_2": "-4.0636391327357750E-004",
}
# A stand-in for astap_cli: writes the .ini that FAKE_ASTAP_INI holds (KEY=value lines)
# under the -o base name, unless the command has a hint and FAKE_ASTAP_HINT_FAILS is
# set, then exits with FAKE_ASTAP_EXIT if set; records its arguments and pid, and can
# sleep first.
FAKE = """\
import os, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_ASTAP_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
if "-h" in args:
    print("ASTAP astrometric solver version CLI-2026.09.01")
    sys.exit(0)
with open(os.environ["FAKE_ASTAP_PID"], "w") as f:
    f.write(str(os.getpid()))
time.sleep(float(os.environ.get("FAKE_ASTAP_SLEEP", "0")))
if "-ra" in args and os.environ.get("FAKE_ASTAP_HINT_FAILS"):
    sys.exit(1)
output = args[args.index("-o") + 1]
with open(output + ".ini", "w") as f:
    f.write(open(os.environ["FAKE_ASTAP_INI"]).read())
if os.environ.get("FAKE_ASTAP_EXIT"):
    sys.exit(int(os.environ["FAKE_ASTAP_EXIT"]))
"""


def install_fake_astap(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Astap:
    """The fake in ``directory`` with D05, answering with the M 8 solution."""
    executable = directory / "astap_cli"
    executable.write_text(f"#!{sys.executable}\n{FAKE}")
    executable.chmod(executable.stat().st_mode | stat.S_IEXEC)
    (directory / "d05_0101.1476").touch()
    ini = directory / "result.ini"
    ini.write_text("".join(f"{key}={value}\n" for key, value in M8.items()))
    monkeypatch.setenv("FAKE_ASTAP_INI", str(ini))
    monkeypatch.setenv("FAKE_ASTAP_LOG", str(directory / "calls.log"))
    monkeypatch.setenv("FAKE_ASTAP_PID", str(directory / "pid"))
    astap = Astap.find(executable)
    assert astap is not None
    return astap


def calls(tmp_path: Path) -> list[list[str]]:
    """The command lines the fake ran, but for its version."""
    log = tmp_path / "calls.log"
    lines = log.read_text().splitlines() if log.exists() else []
    return [line.split() for line in lines if "-h" not in line.split()]


def write_frame(path: Path) -> Path:
    """A FITS file of the M 8 frame's size (the fake does not look at pixels)."""
    header = _fits.Header()
    for key, value in (("SIMPLE", True), ("BITPIX", 16), ("NAXIS", 2)):
        header[key] = value
    header["NAXIS1"] = 6248
    header["NAXIS2"] = 4176
    header.tofile(path)  # only the header: the fake solver never reads pixels
    return path
