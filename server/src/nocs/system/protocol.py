"""What nocsd and nocs-system say to each other over the Unix socket (ADR 0027).

One JSON object per line. A request is ``{"id": <int>, "op": <name>, "args": {…}}``;
its reply ``{"id": <int>, "result": {…}}`` or ``{"id": <int>, "error": {"code",
"message"}}``. ``hello`` tells the protocol version and the operations enabled.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, cast

VERSION = 1
SOCKET = Path("/run/nocs-system/socket")
MAX_LINE = 64 * 1024
"""Bytes in one message, newline included."""

HELLO = "hello"
GROUPS: dict[str, str] = {
    "power.reboot": "power",
    "power.poweroff": "power",
    "hostname.set": "hostname",
    "storage.mount": "storage",
    "storage.eject": "storage",
    "time.set": "time",
}
"""Every operation nocs-system knows, with the group that enables it."""

type ErrorCode = Literal["invalid", "unknown", "disabled", "failed"]
type Message = dict[str, object]

_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


class HelperError(Exception):
    """An operation that nocs-system refused or could not perform."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ErrorCode = code


def validate_hostname(name: str) -> str:
    """A host name as one DNS label, lowercased: it is also the box's mDNS name."""
    name = name.strip().lower()
    if not _HOSTNAME.fullmatch(name):
        raise HelperError(
            "invalid",
            "a name is 1 to 63 letters, digits and hyphens, and does not start or end"
            " with a hyphen",
        )
    return name


def encode(message: Message) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode() + b"\n"


def decode(line: bytes) -> Message:
    """One message; ``HelperError("invalid")`` if it is not a JSON object."""
    try:
        message = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise HelperError("invalid", f"not JSON: {e}") from e
    if not isinstance(message, dict):
        raise HelperError("invalid", "a message is a JSON object")
    return cast(Message, message)
