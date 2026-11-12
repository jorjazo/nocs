"""Owner passphrase, paired devices and observer access, kept in ``auth.json`` (ADR 0014)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import tempfile
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

MIN_PASSPHRASE = 8
MAX_PASSPHRASE = 1024
MAX_NAME = 64

SCRYPT_N = 2**16
"""scrypt cost of new hashes: 64 MiB and 0.22 s on the Pi 5. Stored with each hash."""

_FREE_FAILURES = 5
_MAX_DELAY = 60.0
_LAST_USED_RESOLUTION = timedelta(hours=1)

MAX_TOKENS = 8
"""Cookies a device keeps at once, one per host name it was handed over to (ADR 0044);
a new one beyond these replaces the oldest."""

HANDOFF_TTL = 120.0
"""Seconds a handoff token is valid: enough to rename the box and wait for its new
name to answer (ADR 0044)."""

MAX_HANDOFFS = 4
"""Handoff tokens outstanding at once; a new one beyond these replaces the oldest."""


class AuthError(Exception):
    """A request the current authentication state does not allow."""


class SetupRequiredError(AuthError):
    def __init__(self) -> None:
        super().__init__("no owner passphrase yet: set one up first")


class AlreadySetUpError(AuthError):
    def __init__(self) -> None:
        super().__init__("the owner passphrase is already set")


class WrongPassphraseError(AuthError):
    def __init__(self) -> None:
        super().__init__("wrong passphrase")


class ThrottledError(AuthError):
    def __init__(self, retry_after: float, what: str = "passphrases") -> None:
        super().__init__(f"too many wrong {what}: retry in {retry_after:.0f} s")
        self.retry_after = retry_after


class InvalidHandoffError(AuthError):
    def __init__(self) -> None:
        super().__init__("this handoff is not valid: it expired or was used already")


class ScryptHash(BaseModel):
    n: int
    r: int
    p: int
    salt: str
    hash: str

    @classmethod
    def create(cls, passphrase: str) -> ScryptHash:
        salt = secrets.token_bytes(16)
        params = cls(n=SCRYPT_N, r=8, p=1, salt=_b64(salt), hash="")
        return params.model_copy(update={"hash": _b64(params.derive(passphrase))})

    def derive(self, passphrase: str) -> bytes:
        return hashlib.scrypt(
            passphrase.encode(),
            salt=base64.b64decode(self.salt),
            n=self.n,
            r=self.r,
            p=self.p,
            maxmem=2 * 128 * self.r * self.n,
            dklen=32,
        )

    def matches(self, passphrase: str) -> bool:
        return hmac.compare_digest(self.derive(passphrase), base64.b64decode(self.hash))


class Device(BaseModel):
    id: str
    name: str
    tokens_sha256: list[str] = Field(min_length=1)
    """One cookie per host name the device was handed over to (ADR 0044), oldest first."""
    created: datetime
    last_used: datetime


class _AuthFile(BaseModel):
    passphrase: ScryptHash | None = None
    observer: bool = False
    devices: list[Device] = Field(default_factory=list[Device])


class _Throttle:
    """Free failures, then a doubling wait before the next attempt."""

    def __init__(self, clock: Callable[[], float], what: str) -> None:
        self._clock = clock
        self._what = what
        self._failures = 0
        self._locked_until = 0.0

    def check(self) -> None:
        wait = self._locked_until - self._clock()
        if wait > 0:
            raise ThrottledError(wait, self._what)

    def succeeded(self) -> None:
        self._failures = 0

    def failed(self) -> int:
        """Count a failure; returns how many in a row."""
        self._failures += 1
        if self._failures >= _FREE_FAILURES:
            delay = min(_MAX_DELAY, 2.0 ** (self._failures - _FREE_FAILURES))
            self._locked_until = self._clock() + delay
        return self._failures


@dataclass(frozen=True)
class _Handoff:
    device_id: str
    expires: float


class AuthStore:
    """The single owner's credentials. Not thread-safe: use it from the event loop.

    Handoff tokens (ADR 0044) live only here, in memory, as hashes."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self._path = path
        self._clock = clock
        self._data = _AuthFile()
        if path.exists():
            self._data = _AuthFile.model_validate_json(path.read_text())
        self._by_token = {t: d for d in self._data.devices for t in d.tokens_sha256}
        # One hash at a time: each takes 64 MiB and a fifth of a second on the Pi.
        self._lock = anyio.Lock()
        self._passphrases = _Throttle(clock, "passphrases")
        self._handoff_failures = _Throttle(clock, "handoffs")
        self._handoffs: dict[str, _Handoff] = {}  # by the token's SHA-256, oldest first

    @property
    def setup_required(self) -> bool:
        return self._data.passphrase is None

    @property
    def observer(self) -> bool:
        return self._data.observer and not self.setup_required

    def set_observer(self, enabled: bool) -> None:
        self._data.observer = enabled
        self._save()

    def devices(self) -> list[Device]:
        return list(self._data.devices)

    def device_for(self, token: str) -> Device | None:
        """The device paired with ``token``, if any; notes that it was used."""
        device = self._by_token.get(_sha256(token))
        if device is not None:
            now = _now()
            if now - device.last_used >= _LAST_USED_RESOLUTION:
                device.last_used = now
                self._save()
        return device

    async def setup(self, passphrase: str, name: str) -> tuple[Device, str]:
        """Set the owner passphrase and pair the device that set it."""
        passphrase, name = check_passphrase(passphrase), check_name(name)
        async with self._lock:
            if not self.setup_required:
                raise AlreadySetUpError
            self._data.passphrase = await anyio.to_thread.run_sync(ScryptHash.create, passphrase)
            log.info("owner passphrase set")
            return self._pair(name)

    async def pair(self, passphrase: str, name: str) -> tuple[Device, str]:
        """Pair a new device; returns it with its token, which is not kept."""
        name = check_name(name)
        await self._verify(passphrase)
        return self._pair(name)

    async def change_passphrase(self, current: str, new: str) -> None:
        new = check_passphrase(new)
        await self._verify(current)
        async with self._lock:
            self._data.passphrase = await anyio.to_thread.run_sync(ScryptHash.create, new)
        self._save()
        log.info("owner passphrase changed")

    def revoke(self, device_id: str) -> bool:
        """Unpair a device: every cookie it has, and its pending handoffs."""
        device = self._device(device_id)
        if device is None:
            return False
        self._data.devices.remove(device)
        for token in device.tokens_sha256:
            del self._by_token[token]
        self._handoffs = {k: h for k, h in self._handoffs.items() if h.device_id != device_id}
        self._save()
        log.info("device %s (%s) revoked", device.id, device.name)
        return True

    # -- Handoff to another host name (ADR 0044) ----------------------------------

    def issue_handoff(self, device_id: str) -> str:
        """A one-time token that pairs the browser redeeming it as ``device_id`` under
        the host name it uses then (cookies belong to a host name). Kept only as a hash,
        for :data:`HANDOFF_TTL` seconds."""
        if self._device(device_id) is None:
            raise ValueError(f"no device {device_id}")
        self._expire_handoffs()
        while len(self._handoffs) >= MAX_HANDOFFS:
            del self._handoffs[next(iter(self._handoffs))]
        token = secrets.token_urlsafe(32)
        self._handoffs[_sha256(token)] = _Handoff(device_id, self._clock() + HANDOFF_TTL)
        log.info("handoff issued to device %s", device_id)
        return token

    def redeem_handoff(self, token: str) -> tuple[Device, str]:
        """The device a handoff token was issued to, with a new cookie token for it; the
        handoff is used up. Wrong tokens are throttled like wrong passphrases."""
        self._handoff_failures.check()
        self._expire_handoffs()
        handoff = self._handoffs.pop(_sha256(token), None)
        device = self._device(handoff.device_id) if handoff is not None else None
        if device is None:
            failures = self._handoff_failures.failed()
            log.warning("invalid handoff (%d in a row)", failures)
            raise InvalidHandoffError
        self._handoff_failures.succeeded()
        cookie = secrets.token_urlsafe(32)
        device.tokens_sha256.append(_sha256(cookie))
        self._by_token[device.tokens_sha256[-1]] = device
        while len(device.tokens_sha256) > MAX_TOKENS:
            del self._by_token[device.tokens_sha256.pop(0)]
        device.last_used = _now()
        self._save()
        log.info("device %s (%s) handed over to another host name", device.id, device.name)
        return device, cookie

    def _expire_handoffs(self) -> None:
        now = self._clock()
        self._handoffs = {k: h for k, h in self._handoffs.items() if h.expires > now}

    def _device(self, device_id: str) -> Device | None:
        return next((d for d in self._data.devices if d.id == device_id), None)

    async def _verify(self, passphrase: str) -> None:
        async with self._lock:
            stored = self._data.passphrase
            if stored is None:
                raise SetupRequiredError
            self._passphrases.check()
            normalized = unicodedata.normalize("NFC", passphrase)
            if len(normalized) <= MAX_PASSPHRASE and await anyio.to_thread.run_sync(
                stored.matches, normalized
            ):
                self._passphrases.succeeded()
                return
            failures = self._passphrases.failed()
            log.warning("wrong passphrase (%d in a row)", failures)
            raise WrongPassphraseError

    def _pair(self, name: str) -> tuple[Device, str]:
        token = secrets.token_urlsafe(32)
        now = _now()
        device = Device(
            id=secrets.token_hex(6),
            name=name,
            tokens_sha256=[_sha256(token)],
            created=now,
            last_used=now,
        )
        self._data.devices.append(device)
        self._by_token[device.tokens_sha256[0]] = device
        self._save()
        log.info("device %s (%s) paired", device.id, device.name)
        return device, token

    def _save(self) -> None:
        """Write through a new file (created 0600 by mkstemp), renamed into place."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=f".{self._path.name}.")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(self._data.model_dump_json(indent=2))
            os.replace(tmp, self._path)
        except BaseException:
            os.unlink(tmp)
            raise


def check_passphrase(passphrase: str) -> str:
    normalized = unicodedata.normalize("NFC", passphrase)
    if not MIN_PASSPHRASE <= len(normalized) <= MAX_PASSPHRASE:
        raise ValueError(
            f"the passphrase must have {MIN_PASSPHRASE} to {MAX_PASSPHRASE} characters"
        )
    return normalized


def check_name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= MAX_NAME:
        raise ValueError(f"the device name must have 1 to {MAX_NAME} characters")
    return name


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
