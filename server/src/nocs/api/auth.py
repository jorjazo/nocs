"""Who may call what: the access middleware and the ``/api/auth`` endpoints (ADR 0014)."""

from __future__ import annotations

import contextlib
import ipaddress
import math
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, HTTPException, Request, Response, status
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from nocs.api.schemas import (
    AuthStatus,
    ClientRole,
    ObserverRequest,
    PairedDevice,
    PairRequest,
    PassphraseRequest,
)
from nocs.auth import (
    AlreadySetUpError,
    AuthStore,
    Device,
    SetupRequiredError,
    ThrottledError,
    WrongPassphraseError,
)

COOKIE = "nocs_device"
COOKIE_MAX_AGE = timedelta(days=400)
"""Browsers cap cookie lifetimes at 400 days; ``GET /api/auth`` renews it."""

REVOKED = 4401
"""WebSocket close code when the connection's role is withdrawn."""

type Access = Literal["public", "observer", "owner"]

# Everything under /api not listed here needs the owner (default deny).
_PUBLIC = {
    ("GET", "/api/health"),
    ("GET", "/api/auth"),
    ("POST", "/api/auth/setup"),
    ("POST", "/api/auth/pair"),
}
_OBSERVER = {("GET", "/api/state"), ("WEBSOCKET", "/api/ws"), ("GET", "/api/guiding/steps")}
_OBSERVER_PREFIXES = {("GET", "/api/previews/")}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_SCOPE_KEY = "nocs.identity"


def required_access(method: str, path: str) -> Access:
    if path != "/api" and not path.startswith("/api/"):
        return "public"  # the web app's static files
    method = "GET" if method == "HEAD" else method
    if (method, path) in _PUBLIC:
        return "public"
    if (method, path) in _OBSERVER or any(
        method == m and path.startswith(prefix) for m, prefix in _OBSERVER_PREFIXES
    ):
        return "observer"
    return "owner"


@dataclass(frozen=True)
class Identity:
    role: ClientRole | None
    device: Device | None = None
    token: str | None = None


ANONYMOUS = Identity(role=None)


def identity(connection: HTTPConnection) -> Identity:
    """The identity the middleware gave this request."""
    who = connection.scope.get(_SCOPE_KEY)
    return who if isinstance(who, Identity) else ANONYMOUS


class AuthMiddleware:
    """Checks the host name, origin and role of every request before routing it."""

    def __init__(self, app: ASGIApp, auth: AuthStore, hostnames: Iterable[str] = ()) -> None:
        self._app = app
        self._auth = auth
        self._hostnames = frozenset(_normalize(name) for name in hostnames)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        host = connection.headers.get("host")
        if not allowed_host(host, self._hostnames):
            # A name we do not know may be an attacker's, rebound to this address (DNS
            # rebinding): its pages would pass the Origin check and get their own cookie.
            detail = f"unknown host name {host!r}: add it to NOCS_HOSTNAMES to use it"
            await _deny(scope, receive, send, status.HTTP_421_MISDIRECTED_REQUEST, detail)
            return
        websocket = scope["type"] == "websocket"
        method: str = "WEBSOCKET" if websocket else scope["method"]
        if (websocket or method not in _SAFE_METHODS) and not _same_origin(connection):
            await _deny(scope, receive, send, status.HTTP_403_FORBIDDEN, "cross-origin request")
            return
        who = self._identify(connection)
        needed = required_access(method, scope["path"])
        if (needed == "owner" and who.role != "owner") or (needed == "observer" and not who.role):
            detail = (
                "set up the owner passphrase first"
                if self._auth.setup_required
                else "this device is not paired"
            )
            await _deny(scope, receive, send, status.HTTP_401_UNAUTHORIZED, detail)
            return
        scope[_SCOPE_KEY] = who
        await self._app(scope, receive, send)

    def _identify(self, connection: HTTPConnection) -> Identity:
        token = connection.cookies.get(COOKIE)
        device = self._auth.device_for(token) if token else None
        if device is not None:
            return Identity(role="owner", device=device, token=token)
        return Identity(role="observer") if self._auth.observer else ANONYMOUS


def allowed_host(host: str | None, hostnames: frozenset[str] = frozenset()) -> bool:
    """Whether ``host`` (a Host header) names this server without trusting public DNS:
    an IP address, ``localhost``, an mDNS ``.local`` name, or one of ``hostnames``."""
    if not host:
        return False
    try:
        name = urlsplit(f"//{host}").hostname
    except ValueError:
        return False
    if not name:
        return False
    name = _normalize(name)
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return name == "localhost" or name.endswith(".local") or name in hostnames


def _normalize(name: str) -> str:
    return name.strip().lower().rstrip(".")


def _same_origin(connection: HTTPConnection) -> bool:
    """Whether a browser sent this from the server's own pages (no Origin: not a browser)."""
    origin = connection.headers.get("origin")
    if origin is None:
        return True
    host = connection.headers.get("host")
    return host is not None and urlsplit(origin).netloc.lower() == host.lower()


async def _deny(scope: Scope, receive: Receive, send: Send, code: int, detail: str) -> None:
    if scope["type"] == "websocket":
        # Closing before accepting refuses the handshake (HTTP 403).
        await WebSocketClose(code=1008, reason=detail)(scope, receive, send)
    else:
        await JSONResponse({"detail": detail}, status_code=code)(scope, receive, send)


@dataclass(eq=False)
class _Socket:
    who: Identity
    revoked: anyio.Event = field(default_factory=anyio.Event)


class Sockets:
    """Open WebSockets and the identity each was opened with, to close them when revoked."""

    def __init__(self) -> None:
        self._open: set[_Socket] = set()

    @contextlib.contextmanager
    def track(self, who: Identity) -> Generator[anyio.Event]:
        """Register a WebSocket; the event is set when it must be closed."""
        socket = _Socket(who)
        self._open.add(socket)
        try:
            yield socket.revoked
        finally:
            self._open.discard(socket)

    def revoke_device(self, device_id: str) -> None:
        for socket in self._open:
            if socket.who.device is not None and socket.who.device.id == device_id:
                socket.revoked.set()

    def revoke_observers(self) -> None:
        for socket in self._open:
            if socket.who.role == "observer":
                socket.revoked.set()


def auth_router(auth: AuthStore, sockets: Sockets) -> APIRouter:
    router = APIRouter(prefix="/api/auth")

    @router.get("")
    async def auth_status(  # pyright: ignore[reportUnusedFunction]
        request: Request, response: Response
    ) -> AuthStatus:
        who = identity(request)
        if who.token is not None:
            _set_cookie(request, response, who.token)
        return AuthStatus(
            setup_required=auth.setup_required,
            role=who.role,
            device=_paired(who.device, who) if who.device is not None else None,
            observer=auth.observer,
        )

    @router.post("/setup", status_code=status.HTTP_201_CREATED)
    async def setup(  # pyright: ignore[reportUnusedFunction]
        body: PairRequest, request: Request, response: Response
    ) -> PairedDevice:
        with _auth_errors():
            device, token = await auth.setup(body.passphrase, body.name)
        _set_cookie(request, response, token)
        return _paired(device, Identity(role="owner", device=device))

    @router.post("/pair", status_code=status.HTTP_201_CREATED)
    async def pair(  # pyright: ignore[reportUnusedFunction]
        body: PairRequest, request: Request, response: Response
    ) -> PairedDevice:
        with _auth_errors():
            device, token = await auth.pair(body.passphrase, body.name)
        _set_cookie(request, response, token)
        return _paired(device, Identity(role="owner", device=device))

    @router.get("/devices")
    async def devices(request: Request) -> list[PairedDevice]:  # pyright: ignore[reportUnusedFunction]
        who = identity(request)
        return [_paired(device, who) for device in auth.devices()]

    @router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def revoke(device_id: str, request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        if not auth.revoke(device_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no device {device_id}")
        sockets.revoke_device(device_id)
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        who = identity(request)
        if who.device is not None and who.device.id == device_id:
            response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
        return response

    @router.put("/passphrase", status_code=status.HTTP_204_NO_CONTENT)
    async def change_passphrase(body: PassphraseRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _auth_errors():
            await auth.change_passphrase(body.current, body.new)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/observer", status_code=status.HTTP_204_NO_CONTENT)
    async def observer(body: ObserverRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        auth.set_observer(body.enabled)
        if not body.enabled:
            sockets.revoke_observers()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


def _paired(device: Device, who: Identity) -> PairedDevice:
    return PairedDevice(
        id=device.id,
        name=device.name,
        created=device.created,
        last_used=device.last_used,
        current=who.device is not None and who.device.id == device.id,
    )


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(COOKIE_MAX_AGE.total_seconds()),
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )


@contextlib.contextmanager
def _auth_errors() -> Generator[None]:
    try:
        yield
    except ThrottledError as e:
        retry = str(math.ceil(e.retry_after))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, str(e), headers={"Retry-After": retry}
        ) from e
    except WrongPassphraseError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except (AlreadySetUpError, SetupRequiredError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
