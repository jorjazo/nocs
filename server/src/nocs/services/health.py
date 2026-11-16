"""How the computer is doing, read without privileges (ADR 0027).

Everything comes from files any user can read: hwmon for temperatures, the fan
and the Raspberry Pi's under-voltage alarm (``rpi_volt``), cpufreq for throttling
(the Pi 5 lowers ``scaling_max_freq`` when it is too hot; ``vcgencmd`` needs root
on Ubuntu), ``/proc/stat`` for the CPU's time (busy and in all, since boot: its use
is the difference between two readings), ``/proc/meminfo`` and the root
filesystem's free space. A value the
computer does not report is ``None``: a PC has no under-voltage alarm.

``read_health`` blocks (file system access): call it from a thread.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CPU_SENSORS = ("cpu_thermal", "coretemp", "k10temp", "zenpower")
"""hwmon names of CPU temperature sensors, best first: the Pi's, Intel's, AMD's."""
HOT = 80.0
"""°C: the Pi 5 starts to throttle at 85 °C."""
MEMORY_FULL = 0.9
DISK_LOW = 2_000_000_000
"""Bytes free on the system disk below which NOCS warns (frames have their own reserve)."""


@dataclass(frozen=True, slots=True)
class HealthPaths:
    """Where the kernel publishes it (replaced in tests)."""

    hwmon: Path = Path("/sys/class/hwmon")
    cpufreq: Path = Path("/sys/devices/system/cpu/cpufreq/policy0")
    meminfo: Path = Path("/proc/meminfo")
    stat: Path = Path("/proc/stat")
    root: Path = Path("/")


@dataclass(frozen=True, slots=True)
class Health:
    cpu_temperature: float | None
    """°C."""
    fan: int | None
    """Revolutions per minute."""
    under_voltage: bool | None
    """The supply is too weak right now (Raspberry Pi only)."""
    throttled: bool | None
    """The CPU runs below its top speed because it is too hot or under-powered."""
    memory_used: float | None
    """Fraction of memory in use."""
    cpu_time: tuple[int, int] | None
    """Ticks of all CPUs since boot: busy, and in all."""
    disk_free: int | None
    """Bytes free on the system disk."""


def read_health(paths: HealthPaths) -> Health:
    sensors = _hwmon(paths.hwmon)
    temperature = None
    for name in CPU_SENSORS:
        if name in sensors and (millidegrees := _int(sensors[name] / "temp1_input")) is not None:
            temperature = millidegrees / 1000
            break
    fans = [d for d in sensors.values() if (d / "fan1_input").exists()]
    fan = _int(fans[0] / "fan1_input") if fans else None
    alarm = _int(sensors["rpi_volt"] / "in0_lcrit_alarm") if "rpi_volt" in sensors else None
    top, limit = _int(paths.cpufreq / "cpuinfo_max_freq"), _int(paths.cpufreq / "scaling_max_freq")
    return Health(
        cpu_temperature=temperature,
        fan=fan,
        under_voltage=None if alarm is None else alarm != 0,
        throttled=None if top is None or limit is None else limit < top,
        memory_used=_memory_used(paths.meminfo),
        cpu_time=_cpu_time(paths.stat),
        disk_free=_disk_free(paths.root),
    )


def warnings(health: Health) -> list[str]:
    """What the app should point out, most serious first."""
    found: list[str] = []
    if health.under_voltage:
        found.append("under_voltage")
    if health.throttled:
        found.append("throttled")
    if health.cpu_temperature is not None and health.cpu_temperature >= HOT:
        found.append("hot")
    if health.memory_used is not None and health.memory_used >= MEMORY_FULL:
        found.append("memory")
    if health.disk_free is not None and health.disk_free < DISK_LOW:
        found.append("disk")
    return found


def _hwmon(root: Path) -> dict[str, Path]:
    """hwmon directories by sensor name; the first of each name."""
    sensors: dict[str, Path] = {}
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return sensors
    for entry in entries:
        try:
            name = (entry / "name").read_text().strip()
        except OSError:
            continue
        sensors.setdefault(name, entry)
    return sensors


def _int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def cpu_used(before: tuple[int, int] | None, after: tuple[int, int] | None) -> float | None:
    """Fraction of the CPUs' time spent busy between two readings."""
    if before is None or after is None or after[1] <= before[1]:
        return None
    return min(1.0, max(0.0, (after[0] - before[0]) / (after[1] - before[1])))


def _cpu_time(stat: Path) -> tuple[int, int] | None:
    """The first line of /proc/stat: user nice system idle iowait irq softirq steal …"""
    try:
        with stat.open() as file:
            fields = file.readline().split()
    except OSError:
        return None
    if len(fields) < 9 or fields[0] != "cpu" or not all(f.isdigit() for f in fields[1:9]):
        return None
    ticks = [int(f) for f in fields[1:9]]
    idle = ticks[3] + ticks[4]
    return sum(ticks) - idle, sum(ticks)


def _memory_used(meminfo: Path) -> float | None:
    values: dict[str, int] = {}
    try:
        for line in meminfo.read_text().splitlines():
            key, _, rest = line.partition(":")
            fields = rest.split()
            if fields and fields[0].isdigit():
                values[key] = int(fields[0])
    except OSError:
        return None
    total, available = values.get("MemTotal"), values.get("MemAvailable")
    if not total or available is None:
        return None
    return 1 - available / total


def _disk_free(root: Path) -> int | None:
    try:
        stat = os.statvfs(root)
    except OSError:
        return None
    return stat.f_bavail * stat.f_frsize
