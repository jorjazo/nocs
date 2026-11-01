# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Tonight's target, chosen in the Plan screen: state, file and API."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.config import Settings
from nocs.state import StateStore
from nocs.targets.plan import PlannedTarget, PlanService

SMC = {"id": "NGC 292", "name": "SMC", "ra": 0.8762, "dec": -72.8, "rotation": 30}


def test_the_target_is_kept_and_published(tmp_path: Path) -> None:
    store = StateStore()
    plan = PlanService(store, tmp_path)
    assert store.snapshot()["plan"] == {"target": None}
    plan.set(PlannedTarget.model_validate(SMC))
    assert store.snapshot()["plan"] == {"target": SMC}
    AppState.model_validate(store.snapshot())

    again = StateStore()
    PlanService(again, tmp_path)
    assert again.snapshot()["plan"] == {"target": SMC}

    plan.set(None)
    assert store.snapshot()["plan"] == {"target": None}
    assert not (tmp_path / "plan.json").exists()


def test_an_unreadable_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "plan.json").write_text('{"name": ""}')
    store = StateStore()
    assert PlanService(store, tmp_path).target is None
    assert store.snapshot()["plan"] == {"target": None}


@pytest.fixture
def client(config_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(indi_host="127.0.0.1", indi_port=9))) as client:
        pair_owner(client)
        yield client


def plan_state(client: TestClient) -> dict[str, Any]:
    return client.get("/api/state").json()["state"]["plan"]


def test_choose_and_forget_a_target(client: TestClient) -> None:
    assert plan_state(client) == {"target": None}
    assert client.put("/api/plan/target", json=SMC).status_code == 204
    assert plan_state(client) == {"target": SMC}
    coordinates = {"name": "0h 53m -72 48", "ra": 0.88, "dec": -72.8}
    assert client.put("/api/plan/target", json=coordinates).status_code == 204
    assert plan_state(client)["target"] == {**coordinates, "id": None, "rotation": None}
    assert client.delete("/api/plan/target").status_code == 204
    assert plan_state(client) == {"target": None}


@pytest.mark.parametrize(
    "body",
    [
        {**SMC, "ra": 24},
        {**SMC, "dec": -91},
        {**SMC, "rotation": 360},
        {**SMC, "name": ""},
        {**SMC, "extra": 1},
        {"name": "SMC"},
    ],
)
def test_refuses_bad_targets(client: TestClient, body: dict[str, Any]) -> None:
    assert client.put("/api/plan/target", json=body).status_code == 422


def test_observers_see_the_target_but_cannot_choose(client: TestClient) -> None:
    client.put("/api/plan/target", json=SMC)
    client.put("/api/auth/observer", json={"enabled": True})
    client.cookies.clear()
    assert plan_state(client) == {"target": SMC}
    assert client.put("/api/plan/target", json=SMC).status_code == 401
    assert client.delete("/api/plan/target").status_code == 401
