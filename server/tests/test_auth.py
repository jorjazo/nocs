# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import json
import re
import stat
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from owner import PASSPHRASE, pair_owner
from starlette.websockets import WebSocketDisconnect

from nocs.api import create_app
from nocs.api.auth import COOKIE, REVOKED, allowed_host, required_access
from nocs.auth import AuthStore, ThrottledError, WrongPassphraseError
from nocs.config import Settings


def unreachable_indi() -> Settings:
    return Settings(indi_host="127.0.0.1", indi_port=9)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client of a server in setup mode (no passphrase yet)."""
    with TestClient(create_app(unreachable_indi())) as client:
        yield client


def as_device(token: str) -> dict[str, str]:
    return {"cookie": f"{COOKIE}={token}"}


def pair_other(client: TestClient, name: str) -> str:
    """Pair another device without changing ``client``'s own cookie."""
    mine = httpx.Cookies(client.cookies)
    response = client.post("/api/auth/pair", json={"passphrase": PASSPHRASE, "name": name})
    assert response.status_code == 201, response.text
    client.cookies = mine
    return response.cookies[COOKIE]


def anonymous(client: TestClient) -> TestClient:
    client.cookies.clear()
    return client


# -- Setup mode ----------------------------------------------------------------


def test_setup_mode_allows_only_setup(client: TestClient) -> None:
    assert client.get("/api/auth").json() == {
        "setup_required": True,
        "role": None,
        "device": None,
        "observer": False,
    }
    assert client.get("/api/health").status_code == 200
    response = client.get("/api/state")
    assert response.status_code == 401
    assert "set up" in response.json()["detail"]
    response = client.post("/api/auth/pair", json={"passphrase": PASSPHRASE, "name": "x"})
    assert response.status_code == 409
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/ws"):
        pass


def test_setup_pairs_the_device_that_made_it(client: TestClient) -> None:
    response = client.post("/api/auth/setup", json={"passphrase": PASSPHRASE, "name": "Pixel"})
    assert response.status_code == 201
    device = response.json()
    assert (device["name"], device["current"]) == ("Pixel", True)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Secure" not in cookie  # plain HTTP
    assert response.cookies[COOKIE] not in response.text

    status = client.get("/api/auth").json()
    assert (status["setup_required"], status["role"]) == (False, "owner")
    assert status["device"]["id"] == device["id"]
    assert client.get("/api/state").status_code == 200

    again = client.post("/api/auth/setup", json={"passphrase": "another one", "name": "x"})
    assert again.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"passphrase": "short", "name": "Pixel"},
        {"passphrase": PASSPHRASE, "name": "  "},
        {"passphrase": PASSPHRASE, "name": "x" * 65},
    ],
)
def test_setup_validates(client: TestClient, body: dict[str, str]) -> None:
    assert client.post("/api/auth/setup", json=body).status_code == 422
    assert client.get("/api/auth").json()["setup_required"] is True


def test_status_renews_the_cookie(client: TestClient) -> None:
    pair_owner(client)
    assert COOKIE in client.get("/api/auth").cookies
    assert COOKIE not in anonymous(client).get("/api/auth").cookies


def test_owner_survives_a_restart(config_dir: Path) -> None:
    with TestClient(create_app(unreachable_indi())) as client:
        token = pair_owner(client)
    assert stat.S_IMODE((config_dir / "auth.json").stat().st_mode) == 0o600
    assert token not in (config_dir / "auth.json").read_text()
    with TestClient(create_app(unreachable_indi())) as client:
        assert client.get("/api/auth").json()["setup_required"] is False
        assert client.get("/api/state", headers=as_device(token)).status_code == 200


# -- Pairing and revocation ----------------------------------------------------------


def test_pair_with_the_passphrase(client: TestClient) -> None:
    pair_owner(client, "first")
    anonymous(client)
    response = client.post("/api/auth/pair", json={"passphrase": "wrong one", "name": "x"})
    assert response.status_code == 403
    assert COOKIE not in response.cookies

    pair_owner(client, "second")
    devices = client.get("/api/auth/devices").json()
    assert [(d["name"], d["current"]) for d in devices] == [("first", False), ("second", True)]


def test_wrong_passphrases_are_throttled(client: TestClient) -> None:
    pair_owner(client)
    for _ in range(5):
        response = client.post("/api/auth/pair", json={"passphrase": "wrong one", "name": "x"})
        assert response.status_code == 403
    response = client.post("/api/auth/pair", json={"passphrase": PASSPHRASE, "name": "x"})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
    # Paired devices keep working.
    assert client.get("/api/state").status_code == 200


def test_revoke_another_device(client: TestClient) -> None:
    pair_owner(client)
    other = pair_other(client, "lost phone")
    assert client.get("/api/state", headers=as_device(other)).status_code == 200
    other_id = next(d["id"] for d in client.get("/api/auth/devices").json() if not d["current"])

    response = client.delete(f"/api/auth/devices/{other_id}")
    assert response.status_code == 204
    assert "set-cookie" not in response.headers
    assert client.get("/api/state", headers=as_device(other)).status_code == 401
    assert client.get("/api/state").status_code == 200
    assert client.delete(f"/api/auth/devices/{other_id}").status_code == 404


def test_revoke_own_device_clears_its_cookie(client: TestClient) -> None:
    pair_owner(client)
    me = client.get("/api/auth").json()["device"]["id"]
    response = client.delete(f"/api/auth/devices/{me}")
    assert response.status_code == 204
    assert re.search(rf"{COOKIE}=(\"\")?;", response.headers["set-cookie"])
    assert client.get("/api/auth").json()["role"] is None


def test_revoking_closes_the_device_websocket(client: TestClient) -> None:
    pair_owner(client)
    other = pair_other(client, "tablet")
    other_id = next(d["id"] for d in client.get("/api/auth/devices").json() if not d["current"])
    with client.websocket_connect("/api/ws", headers=as_device(other)) as ws:
        ws.send_text(json.dumps({"type": "hello"}))
        assert ws.receive_json()["type"] == "snapshot"
        assert client.delete(f"/api/auth/devices/{other_id}").status_code == 204
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == REVOKED


def test_change_passphrase(client: TestClient) -> None:
    pair_owner(client)
    new = "a brand new passphrase"
    wrong = client.put("/api/auth/passphrase", json={"current": "wrong one", "new": new})
    assert wrong.status_code == 403
    short = client.put("/api/auth/passphrase", json={"current": PASSPHRASE, "new": "short"})
    assert short.status_code == 422
    changed = client.put("/api/auth/passphrase", json={"current": PASSPHRASE, "new": new})
    assert changed.status_code == 204
    # This device stays paired; pairing now takes the new passphrase.
    assert client.get("/api/state").status_code == 200
    old = client.post("/api/auth/pair", json={"passphrase": PASSPHRASE, "name": "x"})
    assert old.status_code == 403
    assert client.post("/api/auth/pair", json={"passphrase": new, "name": "x"}).status_code == 201


# -- Observer --------------------------------------------------------------------------


def test_observer_is_off_by_default(client: TestClient) -> None:
    pair_owner(client)
    anonymous(client)
    assert client.get("/api/state").status_code == 401
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/ws"):
        pass


def test_observer_watches_but_cannot_command(client: TestClient) -> None:
    token = pair_owner(client)
    assert client.put("/api/auth/observer", json={"enabled": True}).status_code == 204
    anonymous(client)

    status = client.get("/api/auth").json()
    assert (status["role"], status["observer"]) == ("observer", True)
    assert client.get("/api/state").status_code == 200
    assert client.get("/api/previews/none.jpg").status_code == 404  # allowed, just missing
    assert client.get("/api/profiles").status_code == 401
    assert client.post("/api/equipment/disconnect").status_code == 401
    assert client.put("/api/auth/observer", json={"enabled": False}).status_code == 401

    with client.websocket_connect("/api/ws") as ws:
        ws.send_text(json.dumps({"type": "hello"}))
        assert ws.receive_json()["type"] == "snapshot"
        off = client.put("/api/auth/observer", json={"enabled": False}, headers=as_device(token))
        assert off.status_code == 204
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == REVOKED
    assert client.get("/api/state").status_code == 401


def test_every_other_endpoint_needs_the_owner(client: TestClient) -> None:
    """Default deny: anything not explicitly public or for observers refuses observers."""
    pair_owner(client)
    client.put("/api/auth/observer", json={"enabled": True})
    anonymous(client)
    checked = 0
    app = client.app
    assert isinstance(app, FastAPI)
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        path = re.sub(r"\{[^}]+\}", "main_camera", route.path)
        for method in route.methods or ():
            if required_access(method, path) != "owner":
                continue
            response = client.request(method, path, json={})
            assert response.status_code == 401, (method, route.path)
            checked += 1
    assert checked >= 10  # the check really ran


# -- Origin ------------------------------------------------------------------------------


def test_cross_origin_commands_are_refused(client: TestClient) -> None:
    pair_owner(client)
    for origin in ("http://evil.example", "http://testserver.evil", "null"):
        response = client.post("/api/equipment/disconnect", headers={"origin": origin})
        assert response.status_code == 403, origin
    same = client.post("/api/equipment/disconnect", headers={"origin": "http://testserver"})
    assert same.status_code == 202
    # Reads are not CSRF targets (the browser does not let other origins read them).
    assert client.get("/api/state", headers={"origin": "http://evil.example"}).status_code == 200


def test_cross_origin_websocket_is_refused(client: TestClient) -> None:
    pair_owner(client)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/ws", headers={"origin": "http://evil.example"}),
    ):
        pass
    with client.websocket_connect("/api/ws", headers={"origin": "http://testserver"}) as ws:
        ws.send_text(json.dumps({"type": "hello"}))
        assert ws.receive_json()["type"] == "snapshot"


def test_cross_origin_setup_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/auth/setup",
        json={"passphrase": PASSPHRASE, "name": "x"},
        headers={"origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert client.get("/api/auth").json()["setup_required"] is True


# -- Host names (DNS rebinding) ------------------------------------------------------------

EVIL = "http://evil.example.com:8000"


def test_rebound_name_cannot_claim_or_command() -> None:
    """A page whose name the attacker rebinds to the box passes the Origin check."""
    with TestClient(create_app(unreachable_indi()), base_url=EVIL) as evil:
        headers = {"origin": EVIL}
        body = {"passphrase": PASSPHRASE, "name": "attacker"}
        response = evil.post("/api/auth/setup", json=body, headers=headers)
        assert response.status_code == 421
        assert "NOCS_HOSTNAMES" in response.json()["detail"]
        assert evil.get("/api/auth").status_code == 421
        assert evil.get("/").status_code == 421  # the web app too
        with pytest.raises(WebSocketDisconnect), evil.websocket_connect("/api/ws"):
            pass

        # Even with a stolen pairing, the rebound name gets nowhere.
        local = evil.post("http://testserver/api/auth/setup", json=body)
        assert local.status_code == 201
        token = local.cookies[COOKIE]
        command = evil.post("/api/equipment/disconnect", headers={**headers, **as_device(token)})
        assert command.status_code == 421


@pytest.mark.parametrize(
    "host",
    [
        "192.168.4.1",
        "192.168.4.1:8000",
        "[fe80::1]:8000",
        "[::1]",
        "localhost:5173",
        "nocs.local",
        "NOCS-West.local.",
        "nocs.local:8000",
    ],
)
def test_hosts_allowed_by_default(host: str) -> None:
    assert allowed_host(host)


@pytest.mark.parametrize(
    "host",
    [None, "", "evil.example.com", "nocs.local.evil.com", "localhost.evil.com", "testserver", "["],
)
def test_hosts_refused_by_default(host: str | None) -> None:
    assert not allowed_host(host)


def test_configured_hostnames(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOCS_HOSTNAMES", " rig.lan, Nocs.Fritz.Box ,")
    settings = Settings(indi_host="127.0.0.1", indi_port=9)
    assert settings.hostnames == ["rig.lan", "Nocs.Fritz.Box"]
    with TestClient(create_app(settings), base_url="http://nocs.fritz.box:8000") as client:
        assert client.get("/api/auth").status_code == 200
        pair_owner(client)
        assert client.get("/api/state").status_code == 200
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        assert client.get("/api/auth").status_code == 421


# -- Store ------------------------------------------------------------------------------


async def test_throttle_doubles_and_resets(tmp_path: Path) -> None:
    now = [0.0]
    store = AuthStore(tmp_path / "auth.json", clock=lambda: now[0])
    await store.setup(PASSPHRASE, "owner")
    for _ in range(5):
        with pytest.raises(WrongPassphraseError):
            await store.pair("wrong one", "x")
    with pytest.raises(ThrottledError) as throttled:
        await store.pair(PASSPHRASE, "x")
    assert throttled.value.retry_after == pytest.approx(1)

    now[0] += 1
    with pytest.raises(WrongPassphraseError):
        await store.pair("wrong one", "x")
    with pytest.raises(ThrottledError) as throttled:
        await store.pair(PASSPHRASE, "x")
    assert throttled.value.retry_after == pytest.approx(2)

    now[0] += 2
    await store.pair(PASSPHRASE, "x")
    with pytest.raises(WrongPassphraseError):
        await store.pair("wrong one", "x")  # the count started again: no wait


async def test_passphrase_is_normalized(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.json")
    await store.setup("café au lait", "owner")  # é precomposed
    await store.pair("café au lait", "phone")  # e + combining accent
