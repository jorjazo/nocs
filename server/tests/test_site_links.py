# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Google Maps short links, expanded by the box for the site editor."""

import time
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.config import Settings
from nocs.sites import links
from nocs.sites.links import LinkError, LinkUnreachableError, expand, is_short_link

LONG = "https://www.google.com/maps/search/-31.591678,+-71.071358?entry=tts"


def redirects(table: Mapping[str, str | None]) -> links.Fetch:
    def fetch(url: str, timeout: float) -> str | None:
        return table.get(url)

    return fetch


@pytest.mark.parametrize(
    ("url", "short"),
    [
        ("https://maps.app.goo.gl/AbC123", True),
        ("http://maps.app.goo.gl/AbC123?g_st=ic", True),
        ("https://goo.gl/maps/AbC123", True),
        ("https://MAPS.APP.GOO.GL/AbC123", True),
        ("https://maps.app.goo.gl/", False),
        ("https://goo.gl/AbC123", False),
        ("https://maps.app.goo.gl:8080/AbC123", False),
        ("https://user@maps.app.goo.gl/AbC123", False),
        ("https://maps.app.goo.gl.example.com/AbC123", False),
        ("https://example.com/maps.app.goo.gl/AbC123", False),
        ("file:///etc/passwd", False),
        ("http://127.0.0.1/maps/", False),
        ("not a url", False),
    ],
)
def test_only_google_maps_short_links(url: str, short: bool) -> None:
    assert is_short_link(url) is short


async def test_a_short_link_leads_to_its_long_one() -> None:
    assert (
        await expand(
            "https://maps.app.goo.gl/AbC", redirects({"https://maps.app.goo.gl/AbC": LONG})
        )
        == LONG
    )
    # goo.gl/maps first leads to maps.app.goo.gl, then on; a relative Location is fine.
    hops = {
        "https://goo.gl/maps/AbC": "https://maps.app.goo.gl/AbC",
        "https://maps.app.goo.gl/AbC": "/xyz",
        "https://maps.app.goo.gl/xyz": LONG,
    }
    assert await expand("https://goo.gl/maps/AbC", redirects(hops)) == LONG


async def test_links_that_cannot_be_expanded() -> None:
    with pytest.raises(LinkError, match="not a Google Maps short link"):
        await expand("https://example.com/x", redirects({}))
    with pytest.raises(LinkError, match="leads nowhere"):
        await expand(
            "https://maps.app.goo.gl/AbC", redirects({"https://maps.app.goo.gl/AbC": None})
        )
    loop = {"https://maps.app.goo.gl/a": "/b", "https://maps.app.goo.gl/b": "/a"}
    with pytest.raises(LinkError, match="too many"):
        await expand("https://maps.app.goo.gl/a", redirects(loop))

    def offline(url: str, timeout: float) -> str | None:
        raise OSError("Temporary failure in name resolution")

    with pytest.raises(LinkUnreachableError, match="name resolution"):
        await expand("https://maps.app.goo.gl/AbC", offline)

    def hangs(url: str, timeout: float) -> str | None:
        time.sleep(1)
        return LONG

    started = time.monotonic()
    with pytest.raises(LinkUnreachableError, match="in time"):
        await expand("https://maps.app.goo.gl/AbC", hangs, timeout=0.1)
    assert time.monotonic() - started < 0.8


@pytest.fixture
def client(config_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(indi_host="127.0.0.1", indi_port=9))) as client:
        pair_owner(client)
        yield client


def test_maps_link_api(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(links, "_location", redirects({"https://maps.app.goo.gl/AbC": LONG}))
    response = client.post("/api/sites/maps-link", json={"url": "https://maps.app.goo.gl/AbC"})
    assert (response.status_code, response.json()) == (200, {"url": LONG})
    response = client.post("/api/sites/maps-link", json={"url": "http://192.168.1.1/admin"})
    assert response.status_code == 400
    response = client.post("/api/sites/maps-link", json={"url": "https://maps.app.goo.gl/Nope"})
    assert response.status_code == 422

    def offline(url: str, timeout: float) -> str | None:
        raise OSError("Network is unreachable")

    monkeypatch.setattr(links, "_location", offline)
    response = client.post("/api/sites/maps-link", json={"url": "https://maps.app.goo.gl/AbC"})
    assert response.status_code == 502


def test_observers_cannot_expand_links(config_dir: Path) -> None:
    with TestClient(create_app(Settings(indi_host="127.0.0.1", indi_port=9))) as client:
        response = client.post("/api/sites/maps-link", json={"url": "https://maps.app.goo.gl/AbC"})
        assert response.status_code == 401
