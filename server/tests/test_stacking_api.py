# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Live stacking's API: the switch, a new stack and the look, as the state shows them."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(indi_host="127.0.0.1", indi_port=9)
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        yield client


def stack(client: TestClient) -> dict[str, object]:
    state = client.get("/api/state").json()["state"]
    AppState.model_validate(state)
    return state["stack"]


def test_off_until_switched_on(client: TestClient) -> None:
    assert stack(client)["on"] is False
    assert stack(client)["status"] == "off"
    assert client.put("/api/stack", json={"on": True}).status_code == 204
    assert stack(client)["on"] is True
    assert stack(client)["status"] == "idle"
    assert client.put("/api/stack", json={"on": False}).status_code == 204
    assert stack(client)["on"] is False


def test_the_look_is_checked_and_kept(client: TestClient) -> None:
    look = {"background": 0.3, "shadows": -3.0, "saturation": 1.4, "linked": True}
    assert client.put("/api/stack/look", json=look).status_code == 204
    assert stack(client)["look"] == look
    assert client.put("/api/stack/look", json={"background": 2}).status_code == 422


def test_a_new_stack(client: TestClient) -> None:
    assert client.post("/api/stack/reset").status_code == 204
    assert stack(client)["current"] is None


def test_observers_cannot_change_it() -> None:
    with TestClient(create_app(Settings(indi_host="127.0.0.1", indi_port=9))) as client:
        assert client.put("/api/stack", json={"on": True}).status_code == 401
