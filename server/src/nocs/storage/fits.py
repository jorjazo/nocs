"""Completing a frame's FITS header and putting the frame in its place (ADR 0013).

Only the primary header is touched; the pixel data is copied as bytes, never
decoded. Everything here blocks: call it from a thread.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]

# astropy.io.fits has no usable type information: it is used only through this
# untyped handle, and values read from it are converted to typed ones at once.
_fits: Any = fits

BLOCK = 2880
CARD = 80
MAX_HEADER_BLOCKS = 100

type CardValue = str | float | int | bool


class FitsError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Card:
    keyword: str
    value: CardValue
    comment: str


class Header:
    """The primary header of a FITS file, as read from disk."""

    def __init__(self, path: Path) -> None:
        raw = bytearray()
        with open(path, "rb") as f:
            for _ in range(MAX_HEADER_BLOCKS):
                block = f.read(BLOCK)
                if len(block) < BLOCK:
                    raise FitsError(f"{path.name}: truncated FITS header")
                raw += block
                if any(
                    block[i : i + CARD].startswith(b"END")
                    and block[i + 3 : i + CARD].strip() == b""
                    for i in range(0, BLOCK, CARD)
                ):
                    break
            else:
                raise FitsError(f"{path.name}: no END in the FITS header")
        if not raw.startswith(b"SIMPLE"):
            raise FitsError(f"{path.name} is not a FITS file")
        self.length = len(raw)
        """Bytes the header takes on disk, padding included."""
        self._header: Any = _fits.Header.fromstring(bytes(raw).decode("ascii", "replace"))

    def __contains__(self, keyword: str) -> bool:
        return keyword in self._header

    def text(self, keyword: str) -> str | None:
        value: object = self._header.get(keyword)
        return value.strip() or None if isinstance(value, str) else None

    def number(self, keyword: str) -> float | None:
        value: object = self._header.get(keyword)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    def start(self) -> datetime | None:
        """Exposure start (``DATE-OBS``), UTC."""
        value = self.text("DATE-OBS")
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    def apply(self, cards: list[Card], *, overwrite: frozenset[str]) -> None:
        """Add cards the header lacks; replace those in ``overwrite``."""
        for card in cards:
            if card.keyword in overwrite or card.keyword not in self._header:
                self._header[card.keyword] = (card.value, card.comment)

    def encode(self) -> bytes:
        text: str = self._header.tostring(padding=True)
        return text.encode("ascii")


def place(source: Path, header: Header, target: Path) -> None:
    """Write ``header`` into the frame and put it at ``target``, which must not exist.

    When the new header fits in the blocks of the old one (INDI leaves padding),
    it is written in place and the file is moved: a rename on the same filesystem.
    Otherwise the frame is written once at its target with the larger header.
    Never renames over an existing file: ext4 would flush it first (ADR 0012).
    """
    if target.exists():
        raise FileExistsError(target)
    encoded = header.encode()
    if len(encoded) == header.length:
        with open(source, "r+b") as f:
            f.write(encoded)
        shutil.move(source, target)
        return
    with open(source, "rb") as src, open(target, "xb") as dst:
        try:
            dst.write(encoded)
            src.seek(header.length)
            shutil.copyfileobj(src, dst, 1 << 20)
        except BaseException:
            target.unlink(missing_ok=True)  # ours: "x" created it
            raise
    os.unlink(source)
