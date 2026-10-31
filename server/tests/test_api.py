# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.config import Settings
from nocs.state import StateStore


def unreachable_indi() -> Settings:
    # Port 9 (discard) is closed on test machines: the bridge keeps retrying in the background.
    return Settings(indi_host="127.0.0.1", indi_port=9)


@pytest.fixture
def store() -> StateStore:
    return StateStore()


@pytest.fixture
def client(store: StateStore) -> Iterator[TestClient]:
    with TestClient(create_app(unreachable_indi(), store)) as client:
        pair_owner(client)
        yield client


def in_app_loop(client: TestClient, fn: Callable[[], None]) -> None:
    """Run ``fn`` on the application's event loop (the store is not thread-safe)."""
    assert client.portal is not None
    client.portal.call(fn)


def test_health_reports_indi_disconnected(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["indi_connected"] is False


def test_state_snapshot_includes_indi_server(client: TestClient) -> None:
    body = client.get("/api/state").json()
    server = body["state"]["indi"]["server"]
    assert (server["port"], server["connected"]) == (9, False)


def test_set_property_without_indi_is_503(client: TestClient) -> None:
    response = client.post(
        "/api/indi/devices/CCD/properties/CONNECTION", json={"values": {"CONNECT": True}}
    )
    assert response.status_code == 503


def test_center_needs_a_camera_and_a_target(client: TestClient) -> None:
    response = client.post("/api/solver/center", json={"ra": 0.5, "dec": -45})
    assert response.status_code == 503, response.text
    assert client.post("/api/solver/center", json={"ra": 24, "dec": 0}).status_code == 422
    assert client.post("/api/solver/center", json={"dec": 0}).status_code == 422
    bad = {"ra": 1, "dec": 0, "method": "nudge"}
    assert client.post("/api/solver/center", json=bad).status_code == 422


def test_set_property_validates_body(client: TestClient) -> None:
    response = client.post("/api/indi/devices/CCD/properties/CONNECTION", json={"values": {}})
    assert response.status_code == 422


def test_websocket_snapshot_then_patches(client: TestClient, store: StateStore) -> None:
    with client.websocket_connect("/api/ws") as ws:
        ws.send_text(json.dumps({"type": "hello"}))
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        version = snapshot["version"]

        in_app_loop(client, lambda: store.set(("demo", "value"), 42))
        patch = ws.receive_json()
        assert patch == {
            "type": "patch",
            "version": version + 1,
            "ops": [{"op": "set", "path": ["demo", "value"], "value": 42}],
        }


def test_websocket_resume_sends_only_missed_patches(client: TestClient, store: StateStore) -> None:
    def changes() -> None:
        store.set(("a",), 1)
        store.set(("b",), 2)

    in_app_loop(client, changes)
    since = store.version - 1
    with client.websocket_connect("/api/ws") as ws:
        ws.send_text(json.dumps({"type": "hello", "epoch": store.epoch, "since": since}))
        message: dict[str, Any] = ws.receive_json()
        assert message["type"] == "patch"
        assert message["version"] == since + 1
        assert message["ops"][0]["path"] == ["b"]


def test_websocket_ignores_versions_from_another_epoch(
    client: TestClient, store: StateStore
) -> None:
    in_app_loop(client, lambda: store.set(("a",), 1))
    with client.websocket_connect("/api/ws") as ws:
        ws.send_text(json.dumps({"type": "hello", "epoch": "previous-run", "since": 0}))
        message = ws.receive_json()
        assert message["type"] == "snapshot"
        assert message["epoch"] == store.epoch


@pytest.mark.indi
def test_connect_simulator_through_api(indi_address: tuple[str, int]) -> None:
    host, port = indi_address
    with TestClient(create_app(Settings(indi_host=host, indi_port=port))) as client:
        pair_owner(client)
        deadline = time.monotonic() + 10
        while True:
            state = client.get("/api/state").json()["state"]
            devices = state["indi"]["devices"]
            if "Focuser Simulator" in devices:
                break
            assert time.monotonic() < deadline, "simulator devices did not appear"
            time.sleep(0.1)

        response = client.post(
            "/api/indi/devices/Focuser Simulator/properties/CONNECTION",
            json={"values": {"CONNECT": True, "DISCONNECT": False}},
        )
        assert response.status_code == 202

        while True:
            state = client.get("/api/state").json()["state"]
            connection = state["indi"]["devices"]["Focuser Simulator"]["properties"]["CONNECTION"]
            if connection["elements"]["CONNECT"]["value"] is True:
                break
            assert time.monotonic() < deadline + 10, "focuser did not connect"
            time.sleep(0.1)
