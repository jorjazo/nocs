# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Tailscale: the box on a tailnet, its owner's devices paired without the passphrase,
and nocs-system joining and leaving, with a fake ``tailscale`` on the PATH."""

import json
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient
from owner import PASSPHRASE, pair_owner

from nocs.api import create_app
from nocs.api.auth import COOKIE
from nocs.api.schemas import AppState, TailscaleState
from nocs.config import Settings
from nocs.services.tailscale import TailscaleService
from nocs.state import StateStore
from nocs.system.protocol import HelperError, Message
from nocs.system.tailscale import (
    Peer,
    Status,
    Tailscale,
    is_tailnet_address,
    parse_status,
    parse_whois,
)

BOX_IP = "100.101.102.103"
PHONE_IP = "100.64.0.7"
FRIEND_IP = "100.64.0.8"
TAGGED_IP = "100.64.0.9"
OWNER_ID = 1111
BOX_NAME = "nocs.tail-home.ts.net"


def status_json(*, state: str = "Running", tags: list[str] | None = None) -> dict[str, object]:
    """What ``tailscale status --json --peers=false`` says, less what NOCS ignores."""
    if state != "Running":
        return {"BackendState": state, "AuthURL": "", "Self": {"DNSName": "", "UserID": 0}}
    me: dict[str, object] = {
        "DNSName": f"{BOX_NAME}.",
        "HostName": "nocs",
        "TailscaleIPs": [BOX_IP, "fd7a:115c:a1e0::1"],
        "UserID": OWNER_ID,
    }
    if tags:
        me["Tags"] = tags
    return {
        "BackendState": "Running",
        "AuthURL": "",
        "Self": me,
        "User": {str(OWNER_ID): {"ID": OWNER_ID, "LoginName": "owner@example.com"}},
        "CurrentTailnet": {"Name": "owner@example.com", "MagicDNSSuffix": "tail-home.ts.net"},
    }


def whois_json(user: int, login: str, name: str, tags: list[str] | None = None) -> Message:
    node: dict[str, object] = {"Name": f"{name}.tail-home.ts.net.", "ComputedName": name}
    if tags:
        node["Tags"] = tags
    return {"Node": node, "UserProfile": {"ID": user, "LoginName": login}}


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake ``tailscale``: ``status`` prints ``status.json``, ``whois --json <ip>``
    ``whois-<ip>.json`` (else "peer not found"), ``login`` turns the status into
    ``login.json`` and waits like the real one, ``logout`` leaves the tailnet; every call
    goes to ``calls.log``."""
    answers = tmp_path / "answers"
    answers.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "tailscale"
    script.write_text(f"""#!/bin/sh
echo "tailscale $*" >> "{answers}/calls.log"
case "$1" in
  status) cat "{answers}/status.json" ;;
  whois) if [ -f "{answers}/whois-$3.json" ]; then cat "{answers}/whois-$3.json";
         else echo "peer not found" >&2; exit 1; fi ;;
  login) cp "{answers}/login.json" "{answers}/status.json"; exec sleep 30 ;;
  logout) echo '{{"BackendState": "NeedsLogin", "AuthURL": ""}}' > "{answers}/status.json" ;;
esac
""")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    (answers / "status.json").write_text(json.dumps(status_json()))
    whois = {
        PHONE_IP: whois_json(OWNER_ID, "owner@example.com", "pixel-8"),
        FRIEND_IP: whois_json(2222, "friend@example.com", "friends-laptop"),
        TAGGED_IP: whois_json(OWNER_ID, "tagged-devices", "server", tags=["tag:server"]),
    }
    for ip, answer in whois.items():
        (answers / f"whois-{ip}.json").write_text(json.dumps(answer))
    return answers


def calls(tools: Path) -> list[str]:
    log = tools / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


# -- what Tailscale says ---------------------------------------------------------


def test_parse_status() -> None:
    assert parse_status(status_json()) == Status(
        "running",
        name=BOX_NAME,
        ips=(BOX_IP, "fd7a:115c:a1e0::1"),
        tailnet="owner@example.com",
        user_id=OWNER_ID,
        login="owner@example.com",
    )
    tagged = parse_status(status_json(tags=["tag:astro"]))
    assert tagged is not None
    assert (tagged.user_id, tagged.login) == (None, None)
    url = "https://login.tailscale.com/a/abc123"
    assert parse_status({"BackendState": "NeedsLogin", "AuthURL": url}) == Status(
        "needs_login", auth_url=url
    )
    assert parse_status({"BackendState": "NeedsMachineAuth"}) == Status("needs_approval")
    assert parse_status({"BackendState": "Mystery"}) == Status("starting")
    # Only a link to Tailscale's own HTTPS pages is passed on to the app.
    assert parse_status({"BackendState": "NeedsLogin", "AuthURL": "javascript:x"}) == Status(
        "needs_login"
    )
    for nonsense in (None, [], "x", {"BackendState": 3}):
        assert parse_status(nonsense) is None


def test_parse_whois() -> None:
    assert parse_whois(whois_json(OWNER_ID, "owner@example.com", "pixel-8")) == Peer(
        OWNER_ID, "owner@example.com", "pixel-8"
    )
    tagged = parse_whois(whois_json(OWNER_ID, "tagged-devices", "server", tags=["tag:server"]))
    assert tagged == Peer(None, "tagged-devices", "server")
    no_computed = {
        "Node": {"Name": "ipad.tail-home.ts.net."},
        "UserProfile": {"ID": 5, "LoginName": "a@b"},
    }
    assert parse_whois(no_computed) == Peer(5, "a@b", "ipad")
    for nonsense in (None, {}, {"Node": {}, "UserProfile": {"ID": True, "LoginName": "a"}}):
        assert parse_whois(nonsense) is None


@pytest.mark.parametrize(
    ("address", "tailnet"),
    [
        ("100.64.0.1", True),
        ("100.127.255.254", True),
        ("100.128.0.1", False),
        ("192.168.1.10", False),
        ("fd7a:115c:a1e0::5", True),
        ("::ffff:100.64.0.1", True),
        ("fe80::1", False),
        ("testclient", False),
        (None, False),
    ],
)
def test_tailnet_addresses(address: str | None, tailnet: bool) -> None:
    assert is_tailnet_address(address) is tailnet


def test_the_names_of_the_box() -> None:
    box = parse_status(status_json())
    assert box is not None
    for host in (BOX_NAME, "NOCS.tail-home.ts.net.", "nocs", BOX_IP, "fd7a:115c:a1e0::1"):
        assert box.names_box(host), host
    for host in ("nocs.local", "evil.example", "192.168.1.5", "", None):
        assert not box.names_box(host), host


# -- nocsd: the state and the owner -------------------------------------------------


async def test_the_state_says_where_the_box_is(tools: Path) -> None:
    store = StateStore()
    service = TailscaleService(store, perform=_no_helper)
    assert store.get(("tailscale",)) is None
    await service.read()
    state = TailscaleState.model_validate(store.get(("tailscale",)))
    assert state.state == "running"
    assert state.name == BOX_NAME
    assert state.user == "owner@example.com"
    AppState.model_validate(store.snapshot())


async def test_without_tailscale_there_is_no_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    store = StateStore()
    service = TailscaleService(store, perform=_no_helper)
    assert await service.read() is None
    assert store.get(("tailscale",)) is None


async def test_only_the_owners_devices_by_the_boxs_name(tools: Path) -> None:
    service = TailscaleService(StateStore(), perform=_no_helper)
    peer = await service.owner(PHONE_IP, f"{BOX_NAME}:80")
    assert peer == Peer(OWNER_ID, "owner@example.com", "pixel-8")
    assert await service.owner(PHONE_IP, "[fd7a:115c:a1e0::1]:80") == peer
    assert await service.owner(FRIEND_IP, BOX_NAME) is None  # someone else's
    assert await service.owner(TAGGED_IP, BOX_NAME) is None  # a tagged node has no owner
    assert await service.owner("100.64.0.99", BOX_NAME) is None  # not on the tailnet
    assert await service.owner(PHONE_IP, "rebound.example") is None  # DNS rebinding
    assert await service.owner(PHONE_IP, None) is None
    whois_before = sum("whois" in c for c in calls(tools))
    assert await service.owner("192.168.1.20", BOX_NAME) is None  # the LAN: not asked
    assert sum("whois" in c for c in calls(tools)) == whois_before


async def test_a_tagged_box_has_no_owner(tools: Path) -> None:
    (tools / "status.json").write_text(json.dumps(status_json(tags=["tag:astro"])))
    service = TailscaleService(StateStore(), perform=_no_helper)
    assert await service.owner(PHONE_IP, BOX_NAME) is None


async def test_a_box_off_the_tailnet_has_no_owner(tools: Path) -> None:
    (tools / "status.json").write_text(json.dumps(status_json(state="Stopped")))
    service = TailscaleService(StateStore(), perform=_no_helper)
    assert await service.owner(PHONE_IP, BOX_NAME) is None


async def _no_helper(op: str, args: Message) -> Message:
    raise AssertionError(f"{op} {args} reached nocs-system")


# -- the API ----------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(config_dir=tmp_path / "config", data_dir=tmp_path / "data")


def client(settings: Settings, address: str, host: str = BOX_NAME) -> TestClient:
    return TestClient(create_app(settings), base_url=f"http://{host}", client=(address, 50000))


def test_the_owners_phone_pairs_without_the_passphrase(tools: Path, settings: Settings) -> None:
    with TestClient(create_app(settings)) as first:
        pair_owner(first)  # the passphrase is set on the box's network
    with client(settings, PHONE_IP) as phone:
        status = phone.get("/api/auth").json()
        assert status["role"] is None
        assert status["tailscale"] == {"login": "owner@example.com", "device": "pixel-8"}
        response = phone.post("/api/auth/pair/tailscale", json={"name": "Pixel 8"})
        assert response.status_code == 201, response.text
        assert response.json()["name"] == "Pixel 8"
        assert response.cookies[COOKIE]
        status = phone.get("/api/auth").json()
        assert status["role"] == "owner"
        assert status["tailscale"] is None  # paired already
        assert phone.get("/api/state").status_code == 200


def test_tailscale_pairing_is_refused(tools: Path, settings: Settings) -> None:
    with client(settings, PHONE_IP) as phone:
        # Before the passphrase is set: it is set first, on the box's network.
        assert phone.get("/api/auth").json()["tailscale"] is None
        response = phone.post("/api/auth/pair/tailscale", json={"name": "Pixel"})
        assert response.status_code == 409, response.text
        assert (
            phone.post(
                "/api/auth/setup", json={"passphrase": PASSPHRASE, "name": "Pixel"}
            ).status_code
            == 201
        )
    cases = [
        (FRIEND_IP, BOX_NAME),  # another user of the tailnet
        (TAGGED_IP, BOX_NAME),
        (PHONE_IP, "rebound.example"),  # the owner's browser on a page rebound to the box
        ("192.168.1.20", BOX_NAME),  # not from the tailnet
    ]
    for address, host in cases:
        with client(settings, address, host) as other:
            assert other.get("/api/auth").json()["tailscale"] is None
            response = other.post("/api/auth/pair/tailscale", json={"name": "Other"})
            assert response.status_code == 403, (address, host, response.text)
            assert COOKIE not in response.cookies
    with client(settings, PHONE_IP) as phone:
        response = phone.post("/api/auth/pair/tailscale", json={"name": " "})
        assert response.status_code == 422, response.text


def test_join_and_leave_need_nocs_system(tools: Path, settings: Settings) -> None:
    with client(settings, "192.168.1.20", "nocs.local") as owner:
        pair_owner(owner)
        response = owner.post("/api/system/tailscale/login")
        assert response.status_code == 503, response.text
        assert "tailscale.login" in response.json()["detail"]


# -- nocs-system: joining and leaving ---------------------------------------------------


@asynccontextmanager
async def running() -> AsyncGenerator[Tailscale]:
    """nocs-system's actor, running as the helper runs it."""
    actor = Tailscale(link_wait=3.0)
    async with anyio.create_task_group() as tg:
        tg.start_soon(actor.run)
        await anyio.sleep(0.1)
        yield actor
        tg.cancel_scope.cancel()


async def test_login_gives_the_sign_in_link(tools: Path) -> None:
    (tools / "status.json").write_text(json.dumps(status_json(state="NeedsLogin")))
    url = "https://login.tailscale.com/a/abc123"
    (tools / "login.json").write_text(json.dumps({"BackendState": "NeedsLogin", "AuthURL": url}))
    async with running() as actor:
        assert await actor.login({}) == {"auth_url": url, "state": "needs_login"}
        assert "tailscale login --accept-dns=false --timeout=600s" in calls(tools)
        # Asked again while the first one waits: the same link, no second login.
        assert await actor.login({}) == {"auth_url": url, "state": "needs_login"}
        assert sum(c.startswith("tailscale login") for c in calls(tools)) == 1
        assert await actor.logout({}) == {}
        assert "tailscale logout" in calls(tools)


async def test_login_without_internet_gives_up(tools: Path) -> None:
    stuck = json.dumps(status_json(state="NeedsLogin"))
    (tools / "status.json").write_text(stuck)
    (tools / "login.json").write_text(stuck)
    async with running() as actor:
        with pytest.raises(HelperError, match="needs the internet"):
            await actor.login({})


async def test_login_refuses(tools: Path) -> None:
    async with running() as actor:
        with pytest.raises(HelperError, match="already"):
            await actor.login({})  # running already
        with pytest.raises(HelperError, match="unexpected"):
            await actor.login({"key": "x"})
        (tools / "status.json").write_text("tailscaled is not running")
        with pytest.raises(HelperError, match="not running"):
            await actor.login({})
