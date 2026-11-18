"""Google Maps short links, expanded by the box for the site editor.

A short link (``maps.app.goo.gl/…``, ``goo.gl/maps/…``) holds no position: its first
answer is a redirect to the long link, which the web app reads. The browser cannot
follow it itself (no CORS), so nocsd asks for it without following redirects, and
only of Google's short-link hosts: the box never fetches an address a client names.
It needs the internet, which a box in the field often lacks.
"""

from __future__ import annotations

import http.client
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import anyio
import anyio.to_thread

TIMEOUT = 8.0
"""Seconds for the whole expansion, DNS included (a box without internet may hang there)."""

HOPS = 3
"""Redirects followed while they stay on a short-link host."""

type Fetch = Callable[[str, float], str | None]
"""A URL's redirect target (its ``Location``), or None when it answers without one."""


class LinkError(Exception):
    """The link is not a short link, or leads to no long one."""


class LinkUnreachableError(LinkError):
    """Google could not be reached: no internet, most likely."""


def is_short_link(url: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port  # raises for a port that is not a number or out of range
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        return False
    host = (parts.hostname or "").lower()
    if port not in (None, 80, 443):
        return False
    if host == "maps.app.goo.gl":
        return len(parts.path) > 1
    return host == "goo.gl" and parts.path.startswith("/maps/")


def _location(url: str, timeout: float) -> str | None:
    parts = urlsplit(url)
    host = parts.hostname or ""
    connection = (
        http.client.HTTPSConnection(host, timeout=timeout)
        if parts.scheme == "https"
        else http.client.HTTPConnection(host, timeout=timeout)
    )
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    try:
        connection.request("GET", path or "/", headers={"User-Agent": "nocs", "Accept": "*/*"})
        response = connection.getresponse()
        return response.getheader("Location") if 300 <= response.status < 400 else None
    finally:
        connection.close()


async def expand(url: str, fetch: Fetch | None = None, timeout: float = TIMEOUT) -> str:
    """The long link a Google Maps short link leads to."""
    fetch = fetch or _location
    if not is_short_link(url):
        raise LinkError("not a Google Maps short link")
    with anyio.move_on_after(timeout) as scope:
        for _ in range(HOPS):
            try:
                location = await anyio.to_thread.run_sync(
                    fetch, url, timeout, abandon_on_cancel=True
                )
            except (OSError, http.client.HTTPException) as e:
                raise LinkUnreachableError(f"could not open the link: {e}") from e
            if not location:
                raise LinkError("the link leads nowhere")
            url = urljoin(url, location)
            if not is_short_link(url):
                return url
        raise LinkError("the link redirects too many times")
    assert scope.cancel_called
    raise LinkUnreachableError("the link did not answer in time")
