# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The appliance's Wi-Fi (ADR 0028) against a simulated NetworkManager and iw."""

import os
import re
import stat
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner
from test_system import config, serving

from nocs.api import create_app
from nocs.config import Settings
from nocs.system import network as network_module
from nocs.system import operations as operations_module
from nocs.system.network import (
    AP_ID,
    BOOT_GRACE,
    DEFAULT_PASSWORD,
    LOST_GRACE,
    RETRY_STATIONS,
    Network,
    Paths,
    check_country,
    check_password,
    check_ssid,
    in_range,
    split_terse,
    station_id,
)
from nocs.system.operations import Context
from nocs.system.protocol import HelperError
from nocs.system.server import Config


class FakeNetworkManager:
    """What nmcli and iw would answer, and what they were asked."""

    def __init__(self) -> None:
        self.connections: dict[str, dict[str, str]] = {}
        """id → {ssid, mode, psk}, as loaded from keyfiles."""
        self.active: str | None = None
        self.state = "disconnected"
        self.reachable: dict[str, str | None] = {}
        """Networks in range, with their passwords."""
        self.clients = 0
        self.scan = ""
        """``device wifi list`` with SSID, SIGNAL and SECURITY, in terse output."""
        self.exists = True
        self.country: str | None = None
        self.calls: list[tuple[str, ...]] = []

    def known(self, ssid: str, password: str | None = None) -> None:
        self.connections[f"netplan-wlan0-{ssid}"] = {
            "ssid": ssid,
            "mode": "infrastructure",
            "psk": password or "",
        }

    async def run(self, *argv: str, check: bool = True) -> str:
        self.calls.append(argv)
        command = [a for a in argv if a not in ("-t",)]
        match command:
            case ["nmcli", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"]:
                wifi = f"wlan0:wifi:{self.state}:{self.active or ''}\n" if self.exists else ""
                return f"{wifi}eth0:ethernet:unavailable:\n"
            case ["nmcli", "-f", "NAME,TYPE", "connection", "show"]:
                return "".join(f"{name}:802-11-wireless\n" for name in self.connections)
            case ["nmcli", "-g", _, "connection", "show", "id", name]:
                # One value per line, as nmcli 1.54 prints a connection's fields.
                c = self.connections[name]
                return f"{c['ssid']}\n{c['mode']}\n"
            case ["nmcli", "connection", "load", path]:
                text = Path(path).read_text()  # noqa: ASYNC240 (a fake, in tests)
                fields = dict(re.findall(r"^(\w+)=(.*)$", text, re.M))
                self.connections[fields["id"]] = {
                    "ssid": fields["ssid"],
                    "mode": fields["mode"],
                    "psk": fields.get("psk", ""),
                }
                return ""
            case ["nmcli", "--wait", _, "connection", "up", "id", name]:
                c = self.connections[name]
                if c["mode"] == "ap" or self.reachable.get(c["ssid"], "missing") == (
                    c["psk"] or None
                ):
                    self.active, self.state = name, "connected"
                    return ""
                self.active, self.state = None, "disconnected"
                return self.fail(
                    check, "Error: Connection activation failed: Secrets were required"
                )
            case ["nmcli", "connection", "down", "id", _]:
                self.active, self.state = None, "disconnected"
                return ""
            case ["nmcli", "connection", "delete", "id", name]:
                self.connections.pop(name, None)
                return ""
            case ["nmcli", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes"]:
                return "".join(f"{ssid}\n" for ssid in self.reachable)
            case [
                "nmcli",
                "--wait",
                _,
                "-f",
                "SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                "ifname",
                "wlan0",
                "--rescan",
                _,
            ]:
                return self.scan
            case ["iw", "dev", "wlan0", "station", "dump"]:
                return "".join(
                    f"Station 00:11:22:33:44:{i:02x} (on wlan0)\n" for i in range(self.clients)
                )
            case ["iw", "reg", "set", country]:
                self.country = country
                return ""
            case _:
                raise AssertionError(f"unexpected command: {argv}")

    @staticmethod
    def fail(check: bool, message: str) -> str:
        if check:
            raise HelperError("failed", f"nmcli: {message}")
        return ""

    def ap_is_up(self) -> bool:
        return self.active == AP_ID and self.state == "connected"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def nm(monkeypatch: pytest.MonkeyPatch) -> FakeNetworkManager:
    fake = FakeNetworkManager()
    monkeypatch.setattr(network_module, "_run", fake.run)
    monkeypatch.setattr(network_module, "JOIN_DELAY", 0.0)
    monkeypatch.setattr(network_module.socket, "gethostname", lambda: "nocs")
    return fake


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    (tmp_path / "serial-number").write_text("10000000a1b2c3d4\0")
    return Paths(
        state=tmp_path / "state/network.json",
        connections=tmp_path / "connections",
        dnsmasq=tmp_path / "dnsmasq-shared.d/nocs.conf",
        serial=tmp_path / "serial-number",
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


def make(paths: Paths, clock: Clock) -> Network:
    return Network(paths, monotonic=clock)


async def test_at_boot_known_networks_get_a_minute_then_the_access_point(
    nm: FakeNetworkManager, paths: Paths, clock: Clock
) -> None:
    network = make(paths, clock)
    await network.tick()
    assert not nm.ap_is_up()
    clock.now += BOOT_GRACE
    await network.tick()
    assert nm.ap_is_up()
    ap = nm.connections[AP_ID]
    assert (ap["ssid"], ap["mode"], ap["psk"]) == ("NOCS-C3D4", "ap", DEFAULT_PASSWORD)
    assert paths.dnsmasq.read_text() == "address=/nocs.local/10.42.0.1\naddress=/nocs/10.42.0.1\n"
    keyfile = paths.connections / f"{AP_ID}.nmconnection"
    assert stat.S_IMODE(keyfile.stat().st_mode) == 0o600
    assert not any(DEFAULT_PASSWORD in " ".join(call) for call in nm.calls)


async def test_a_lost_station_gives_way_to_the_access_point(
    nm: FakeNetworkManager, paths: Paths, clock: Clock
) -> None:
    nm.known("Home", "home-secret")
    nm.active, nm.state = "netplan-wlan0-Home", "connected"
    network = make(paths, clock)
    await network.tick()
    nm.active, nm.state = None, "disconnected"
    await network.tick()
    clock.now += LOST_GRACE - 1
    await network.tick()
    assert not nm.ap_is_up()
    clock.now += 1
    await network.tick()
    assert nm.ap_is_up()


async def test_the_access_point_is_left_only_without_clients(
    nm: FakeNetworkManager, paths: Paths, clock: Clock
) -> None:
    nm.known("Home", "home-secret")
    network = make(paths, clock)
    clock.now += BOOT_GRACE
    await network.tick()
    assert nm.ap_is_up()
    nm.reachable = {"Home": "home-secret"}
    nm.clients = 1
    clock.now += RETRY_STATIONS
    await network.tick()
    assert nm.ap_is_up()  # a phone is on it
    nm.clients = 0
    await network.tick()
    assert nm.active == "netplan-wlan0-Home"


async def test_join_a_network(nm: FakeNetworkManager, paths: Paths, clock: Clock) -> None:
    network = make(paths, clock)
    clock.now += BOOT_GRACE
    await network.tick()
    nm.reachable = {"Casa Pérez": "casa-12345"}
    assert await network.join({"ssid": "Casa Pérez", "password": "casa-12345"}) == {
        "accepted": True
    }
    assert (await network.status({}))["joining"] == "Casa Pérez"
    await network.tick()
    assert nm.active == station_id("Casa Pérez")
    status = await network.status({})
    assert (status["mode"], status["ssid"], status["joining"]) == ("station", "Casa Pérez", None)
    last = status["last_join"]
    assert isinstance(last, dict)
    assert (last["ssid"], last["ok"], last["error"]) == ("Casa Pérez", True, None)
    assert not any("casa-12345" in " ".join(call) for call in nm.calls)


async def test_a_failed_join_comes_back_as_the_access_point(
    nm: FakeNetworkManager, paths: Paths, clock: Clock
) -> None:
    network = make(paths, clock)
    nm.reachable = {"Home": "the-right-one"}
    await network.join({"ssid": "Home", "password": "a-wrong-one"})
    await network.tick()
    assert nm.ap_is_up()
    assert station_id("Home") not in nm.connections  # not retried with the wrong password
    last = (await network.status({}))["last_join"]
    assert isinstance(last, dict)
    assert last["ok"] is False
    assert "Secrets were required" in str(last["error"])


async def test_pinned_modes(nm: FakeNetworkManager, paths: Paths, clock: Clock) -> None:
    nm.known("Home", "home-secret")
    nm.active, nm.state = "netplan-wlan0-Home", "connected"
    network = make(paths, clock)
    await network.set_mode({"pin": "ap"})
    await network.tick()
    assert nm.ap_is_up()
    await network.set_mode({"pin": "station"})
    await network.tick()
    assert nm.state == "disconnected"
    clock.now += BOOT_GRACE * 10
    await network.tick()
    assert not nm.ap_is_up()  # pinned: never falls back
    assert make(paths, clock).status  # the pin is kept for the next start
    assert '"pin": "station"' in paths.state.read_text()
    assert stat.S_IMODE(paths.state.stat().st_mode) == 0o600


async def test_the_access_point_changes_at_once(
    nm: FakeNetworkManager, paths: Paths, clock: Clock
) -> None:
    network = make(paths, clock)
    await network.set_mode({"pin": "ap"})
    await network.tick()
    await network.access_point({"ssid": "Rig West", "password": "dark-skies-1", "country": "CL"})
    assert nm.connections[AP_ID]["psk"] == DEFAULT_PASSWORD  # the reply goes out first
    await network.tick()
    ap = nm.connections[AP_ID]
    assert (ap["ssid"], ap["psk"], nm.country) == ("Rig West", "dark-skies-1", "CL")
    status = await network.status({})
    assert (status["ap_ssid"], status["ap_default_password"], status["country"]) == (
        "Rig West",
        False,
        "CL",
    )
    assert "dark-skies-1" not in str(status)
    with pytest.raises(HelperError, match="8 to 63"):
        await network.access_point({"password": "short"})


async def test_the_first_run_may_keep_the_default_password(
    nm: FakeNetworkManager, paths: Paths, clock: Clock
) -> None:
    network = make(paths, clock)
    status = await network.status({})
    assert (status["set_up"], status["ap_default_password"]) == (False, True)
    await network.access_point({"password": DEFAULT_PASSWORD, "country": "CL"})
    status = await network.status({})
    assert (status["set_up"], status["ap_default_password"]) == (True, True)
    assert (await make(paths, clock).status({}))["set_up"]  # kept for the next start


async def test_forget(nm: FakeNetworkManager, paths: Paths, clock: Clock) -> None:
    nm.known("Home", "home-secret")
    nm.known("Office", "office-secret")
    network = make(paths, clock)
    await network.forget({"ssid": "Home"})
    assert (await network.status({}))["known"] == ["Office"]


def test_networks_in_range() -> None:
    output = "\n".join(
        [
            "Home:48:WPA2",
            "Home:81:WPA2",  # a second access point of the same network
            r"Café\:2:81:WPA1 WPA2",
            "::WPA2",  # hidden
            "Plaza:30:",  # open
            "NOCS-C3D4:99:WPA2",
        ]
    )
    assert in_range(output, exclude="NOCS-C3D4") == [
        {"ssid": "Café:2", "signal": 81, "secured": True},
        {"ssid": "Home", "signal": 81, "secured": True},
        {"ssid": "Plaza", "signal": 30, "secured": False},
    ]


async def test_scan_when_asked(nm: FakeNetworkManager, paths: Paths, clock: Clock) -> None:
    nm.scan = "Home:70:WPA2\nNOCS-C3D4:99:WPA2\n"
    network = make(paths, clock)
    assert await network.scan({}) == {"networks": [{"ssid": "Home", "signal": 70, "secured": True}]}
    assert nm.calls[-1][-2:] == ("--rescan", "yes")
    # While the box is about to leave for a network, the last results, no new scan.
    await network.join({"ssid": "Home", "password": "home-secret"})
    await network.scan({})
    assert nm.calls[-1][-2:] == ("--rescan", "no")
    with pytest.raises(HelperError):
        await network.scan({"band": "5"})
    nm.exists = False
    assert await network.scan({}) == {"networks": []}


@pytest.mark.parametrize("ssid", ["", "x" * 33, "a;b", "a\\b", "line\nbreak", 7])
def test_bad_network_names(ssid: object) -> None:
    with pytest.raises(HelperError):
        check_ssid(ssid)


def test_names_passwords_and_countries() -> None:
    assert check_ssid("Casa Pérez") == "Casa Pérez"
    assert check_password("12345678") == "12345678"
    for bad in ("1234567", "x" * 64, "contraseña", None):
        with pytest.raises(HelperError):
            check_password(bad)
    assert check_country("CL") == "CL"
    assert check_country("00") == "00"  # the world domain, before the first run
    for bad in ("cl", "CHL", "", None, "XX", "EU", ["CL"]):
        with pytest.raises(HelperError):
            check_country(bad)


def test_nmcli_terse_fields() -> None:
    assert split_terse(r"wlan0:wifi:connected:My\:Net") == ["wlan0", "wifi", "connected", "My:Net"]
    assert split_terse(r"a\\b:c") == ["a\\b", "c"]


def test_station_ids_are_safe_file_names() -> None:
    name = station_id("../../etc; rm -rf")
    assert re.fullmatch(r"nocs-[A-Za-z0-9_-]+", name)
    assert os.sep not in name


def test_the_api_publishes_and_joins(nm: FakeNetworkManager, paths: Paths, tmp_path: Path) -> None:
    cfg = config(tmp_path, enabled=frozenset({"network"}))
    cfg = Config(
        uid=cfg.uid,
        gid=cfg.gid,
        enabled=cfg.enabled,
        socket=cfg.socket,
        context=Context(network=Network(paths)),
    )
    nm.reachable = {"Home": "home-secret"}
    with serving(cfg):
        settings = Settings(
            indi_host="127.0.0.1",
            indi_port=9,
            gpsd_port=9,
            config_dir=tmp_path / "config",
            data_dir=tmp_path / "data",
            system_socket=cfg.socket,
        )
        with TestClient(create_app(settings)) as client:
            pair_owner(client)
            response = client.post(
                "/api/system/network/join", json={"ssid": "Home", "password": "home-secret"}
            )
            assert response.status_code == 202, response.text
            network = client.get("/api/state").json()["state"]["network"]
            assert network["ap_ssid"] == "NOCS-C3D4"
            assert (network["set_up"], network["ap_default_password"]) == (False, True)
            response = client.put("/api/system/network/access-point", json={"password": "short"})
            assert response.status_code == 422
            assert "8 to 63" in response.json()["detail"]
            response = client.post(
                "/api/system/network/setup", json={"country": "XX", "password": "dark-skies-1"}
            )
            assert response.status_code == 422
            assert "the radio knows" in response.text
            response = client.post(
                "/api/system/network/setup", json={"country": "cl", "password": "dark-skies-1"}
            )
            assert response.status_code == 202, response.text
            network = client.get("/api/state").json()["state"]["network"]
            assert (network["set_up"], network["ap_default_password"]) == (True, False)
            assert network["country"] == "CL"
            nm.scan = "Home:64:WPA2\nPlaza:20:\n"
            response = client.post("/api/system/network/scan")
            assert response.status_code == 200, response.text
            assert response.json() == [
                {"ssid": "Home", "signal": 64, "secured": True},
                {"ssid": "Plaza", "signal": 20, "secured": False},
            ]


def test_the_first_run_names_the_box_and_checks_everything_first(
    nm: FakeNetworkManager, paths: Paths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    renamed: list[tuple[str, ...]] = []
    host = ["nocs"]

    async def run(*argv: str) -> str:
        if argv[0] == "hostnamectl":
            renamed.append(argv)
            host[0] = argv[-1]
        return ""

    monkeypatch.setattr(operations_module, "run", run)
    monkeypatch.setattr(network_module.socket, "gethostname", lambda: host[0])
    nm.connections[AP_ID] = {"ssid": "NOCS-C3D4", "mode": "ap", "psk": DEFAULT_PASSWORD}
    nm.active, nm.state, nm.clients = AP_ID, "connected", 1  # this phone, on the access point
    cfg = config(tmp_path, enabled=frozenset({"network", "hostname"}))
    cfg = Config(
        uid=cfg.uid,
        gid=cfg.gid,
        enabled=cfg.enabled,
        socket=cfg.socket,
        context=replace(cfg.context, network=Network(paths)),
    )
    with serving(cfg):
        settings = Settings(
            indi_host="127.0.0.1",
            indi_port=9,
            gpsd_port=9,
            config_dir=tmp_path / "config",
            data_dir=tmp_path / "data",
            system_socket=cfg.socket,
        )
        with TestClient(create_app(settings)) as client:
            pair_owner(client)
            setup = {"country": "CL", "password": "dark-skies-1"}
            # A mistake in any step changes nothing, the name included.
            for bad, detail in (
                ({"hostname": "rig 2"}, "hyphens"),
                ({"hostname": "rig-2", "password": "short"}, "8 to 63"),
                ({"hostname": "rig-2", "join": {"ssid": "a;b"}}, "no control characters"),
                ({"hostname": "rig-2", "join": {"ssid": "Home", "password": "short"}}, "8 to 63"),
            ):
                response = client.post("/api/system/network/setup", json=setup | bad)
                assert response.status_code == 422, bad
                assert detail in response.json()["detail"]
            assert renamed == []
            assert client.get("/api/state").json()["state"]["network"]["set_up"] is False
            # The name it has already: not renamed again.
            response = client.post("/api/system/network/setup", json=setup | {"hostname": "nocs"})
            assert response.status_code == 202, response.text
            assert renamed == []
            response = client.post(
                "/api/system/network/setup", json=setup | {"hostname": " Rig-West "}
            )
            assert response.status_code == 202, response.text
            assert renamed == [("hostnamectl", "set-hostname", "rig-west")]
            assert "127.0.1.1\trig-west" in cfg.context.hosts.read_text()
            # Renamed first: the access point restarts under the new name, which its
            # DNS gives phones that do not ask mDNS.
            for _ in range(100):
                if paths.dnsmasq.exists() and "rig-west.local" in paths.dnsmasq.read_text():
                    break
                time.sleep(0.05)
            assert paths.dnsmasq.read_text() == (
                "address=/rig-west.local/10.42.0.1\naddress=/rig-west/10.42.0.1\n"
            )
            assert nm.ap_is_up()
            assert nm.connections[AP_ID]["psk"] == "dark-skies-1"
