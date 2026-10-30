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
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"too many wrong passphrases: retry in {retry_after:.0f} s")
        self.retry_after = retry_after


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
    token_sha256: str
    created: datetime
    last_used: datetime


class _AuthFile(BaseModel):
    passphrase: ScryptHash | None = None
    observer: bool = False
    devices: list[Device] = Field(default_factory=list[Device])


class AuthStore:
    """The single owner's credentials. Not thread-safe: use it from the event loop."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self._path = path
        self._clock = clock
        self._data = _AuthFile()
        if path.exists():
            self._data = _AuthFile.model_validate_json(path.read_text())
        self._by_token = {d.token_sha256: d for d in self._data.devices}
        # One hash at a time: each takes 64 MiB and a fifth of a second on the Pi.
        self._lock = anyio.Lock()
        self._failures = 0
        self._locked_until = 0.0

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
        device = next((d for d in self._data.devices if d.id == device_id), None)
        if device is None:
            return False
        self._data.devices.remove(device)
        del self._by_token[device.token_sha256]
        self._save()
        log.info("device %s (%s) revoked", device.id, device.name)
        return True

    async def _verify(self, passphrase: str) -> None:
        async with self._lock:
            stored = self._data.passphrase
            if stored is None:
                raise SetupRequiredError
            wait = self._locked_until - self._clock()
            if wait > 0:
                raise ThrottledError(wait)
            normalized = unicodedata.normalize("NFC", passphrase)
            if len(normalized) <= MAX_PASSPHRASE and await anyio.to_thread.run_sync(
                stored.matches, normalized
            ):
                self._failures = 0
                return
            self._failures += 1
            if self._failures >= _FREE_FAILURES:
                delay = min(_MAX_DELAY, 2.0 ** (self._failures - _FREE_FAILURES))
                self._locked_until = self._clock() + delay
            log.warning("wrong passphrase (%d in a row)", self._failures)
            raise WrongPassphraseError

    def _pair(self, name: str) -> tuple[Device, str]:
        token = secrets.token_urlsafe(32)
        now = _now()
        device = Device(
            id=secrets.token_hex(6),
            name=name,
            token_sha256=_sha256(token),
            created=now,
            last_used=now,
        )
        self._data.devices.append(device)
        self._by_token[device.token_sha256] = device
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
