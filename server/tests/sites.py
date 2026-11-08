# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The box's active site for API tests (ADR 0038)."""

from typing import Any

from fastapi.testclient import TestClient


def use_site(client: TestClient, site: dict[str, Any]) -> str:
    """Save ``site`` and make it the active one; returns its id."""
    response = client.post("/api/sites", json=site)
    assert response.status_code == 201, response.text
    site_id: str = response.json()["id"]
    response = client.put("/api/sites/active", json={"id": site_id})
    assert response.status_code == 204, response.text
    return site_id
