# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Pair test clients with the API, which only answers its owner (ADR 0014)."""

from fastapi.testclient import TestClient

from nocs.api.auth import COOKIE

PASSPHRASE = "correct horse battery"


def pair_owner(client: TestClient, name: str = "tests") -> str:
    """Set up the passphrase if needed and pair ``client``; returns its device token."""
    if client.get("/api/auth").json()["setup_required"]:
        response = client.post("/api/auth/setup", json={"passphrase": PASSPHRASE, "name": name})
    else:
        response = client.post("/api/auth/pair", json={"passphrase": PASSPHRASE, "name": name})
    assert response.status_code == 201, response.text
    return response.cookies[COOKIE]
