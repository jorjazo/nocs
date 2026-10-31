"""Health readings from a fake /sys and /proc, and the diagnostics bundle."""

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from nocs.api.schemas import SystemState
from nocs.jobs import JobManager
from nocs.services.diagnostics import build
from nocs.services.health import HealthPaths, read_health, warnings
from nocs.services.system import SystemService
from nocs.state import StateStore

MEMINFO = "MemTotal:        8121344 kB\nMemFree:         4048000 kB\nMemAvailable:    6748000 kB\n"


def fake_sys(
    tmp_path: Path,
    sensors: dict[str, dict[str, str]],
    max_freq: int = 2400000,
    limit: int = 2400000,
) -> HealthPaths:
    hwmon = tmp_path / "hwmon"
    for i, (name, files) in enumerate(sensors.items()):
        directory = hwmon / f"hwmon{i}"
        directory.mkdir(parents=True)
        (directory / "name").write_text(f"{name}\n")
        for file, value in files.items():
            (directory / file).write_text(f"{value}\n")
    cpufreq = tmp_path / "cpufreq"
    cpufreq.mkdir()
    (cpufreq / "cpuinfo_max_freq").write_text(f"{max_freq}\n")
    (cpufreq / "scaling_max_freq").write_text(f"{limit}\n")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(MEMINFO)
    return HealthPaths(hwmon=hwmon, cpufreq=cpufreq, meminfo=meminfo, root=tmp_path)


# As the lab Pi 5 reported them.
PI5 = {
    "cpu_thermal": {"temp1_input": "57850"},
    "rpi_volt": {"in0_lcrit_alarm": "0"},
    "rp1_adc": {"temp1_input": "58958", "in1_input": "1473"},
    "pwmfan": {"fan1_input": "2211", "pwm1": "75"},
}


def test_a_pi_5(tmp_path: Path) -> None:
    health = read_health(fake_sys(tmp_path, PI5, limit=2400000))
    assert health.cpu_temperature == 57.85
    assert health.fan == 2211
    assert (health.under_voltage, health.throttled) == (False, False)
    assert health.memory_used is not None
    assert round(health.memory_used, 3) == 0.169
    assert health.disk_free is not None
    assert health.disk_free > 0
    assert warnings(health) == []


def test_an_under_powered_hot_pi(tmp_path: Path) -> None:
    sensors = PI5 | {
        "cpu_thermal": {"temp1_input": "84100"},
        "rpi_volt": {"in0_lcrit_alarm": "1"},
    }
    health = read_health(fake_sys(tmp_path, sensors, limit=1500000))
    assert (health.under_voltage, health.throttled) == (True, True)
    assert warnings(health) == ["under_voltage", "throttled", "hot"]


def test_a_pc_reports_no_under_voltage(tmp_path: Path) -> None:
    health = read_health(fake_sys(tmp_path, {"acpitz": {}, "coretemp": {"temp1_input": "45000"}}))
    assert health.cpu_temperature == 45.0
    assert (health.under_voltage, health.fan) == (None, None)


def test_nothing_readable(tmp_path: Path) -> None:
    paths = HealthPaths(
        hwmon=tmp_path / "none", cpufreq=tmp_path / "none", meminfo=tmp_path / "none", root=tmp_path
    )
    health = read_health(paths)
    assert (health.cpu_temperature, health.fan, health.under_voltage) == (None, None, None)
    assert (health.throttled, health.memory_used) == (None, None)


async def test_service_rounds_and_remembers_under_voltage(tmp_path: Path) -> None:
    store = StateStore()
    sensors = PI5 | {"rpi_volt": {"in0_lcrit_alarm": "1"}}
    paths = fake_sys(tmp_path, sensors)
    service = SystemService(store, JobManager(store), tmp_path / "missing.sock", paths)
    await service.sample()
    health = SystemState.model_validate(store.get(("system",))).health
    assert health is not None
    assert (health.cpu_temperature, health.fan, health.memory_used) == (58, 2200, 17)
    assert health.under_voltage is True
    seen = health.under_voltage_seen
    assert seen is not None

    (tmp_path / "hwmon" / "hwmon1" / "in0_lcrit_alarm").write_text("0\n")
    await service.sample()
    health = SystemState.model_validate(store.get(("system",))).health
    assert health is not None
    assert (health.under_voltage, health.under_voltage_seen) == (False, seen)


async def test_samples_that_round_the_same_change_nothing(tmp_path: Path) -> None:
    store = StateStore()
    paths = fake_sys(tmp_path, PI5)
    service = SystemService(store, JobManager(store), tmp_path / "missing.sock", paths)
    await service.sample()
    version = store.version
    (tmp_path / "hwmon" / "hwmon0" / "temp1_input").write_text("58100\n")
    (tmp_path / "hwmon" / "hwmon3" / "fan1_input").write_text("2190\n")
    await service.sample()
    assert store.version == version


def test_diagnostics_bundle() -> None:
    name, data = build(
        {"system": {"hostname": "nocs"}}, "nocs", datetime(2026, 11, 1, 3, 4, 5, tzinfo=UTC)
    )
    assert name == "nocs-diagnostics-nocs-20261101-030405.zip"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {Path(n).name: archive.read(n).decode() for n in archive.namelist()}
    assert set(files) == {"versions.txt", "state.json", "journal.txt"}
    assert files["versions.txt"].startswith("nocs ")
    assert json.loads(files["state.json"]) == {"system": {"hostname": "nocs"}}
