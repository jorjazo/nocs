"""How names and designations are written loosely: folding text and keying ids."""

from __future__ import annotations

import re
import unicodedata

# Catalog names as people write them in full, and OpenNGC's own spellings, keyed
# by the prefix NOCS shows.
_PREFIX_SYNONYMS = {
    "messier": "m",
    "caldwell": "c",
    "melotte": "mel",
    "collinder": "cr",
    "cl": "cr",  # OpenNGC writes Collinder as Cl
    "barnard": "b",
    "harvard": "h",
}

_RUNS = re.compile(r"[a-z]+|\d+")
_NOT_WORD = re.compile(r"[^a-z0-9]+")


def fold(text: str) -> str:
    """Lower case, no accents or apostrophes, words separated by single spaces.

    "Nebulosa de Orión" and "nebulosa de orion" fold alike, as do "Cat's Eye" and
    "cats eye".
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    plain = plain.replace("'", "").replace("\N{RIGHT SINGLE QUOTATION MARK}", "")
    return _NOT_WORD.sub(" ", plain).strip()


def id_key(text: str) -> str | None:
    """A designation reduced to what identifies it, or None if it is not one.

    "M 31", "m31", "Messier 31" and "M031" all give ``m31``; "NGC 0292" and "ngc292"
    give ``ngc292``; "ESO 56-115" gives ``eso56-115``. A designation starts with a
    catalog's letters and has at least one number.
    """
    runs = _RUNS.findall(fold(text))
    if len(runs) < 2 or not runs[0].isalpha() or not any(r.isdigit() for r in runs):
        return None
    runs[0] = _PREFIX_SYNONYMS.get(runs[0], runs[0])
    key = ""
    previous_digit = False
    for run in runs:
        digit = run.isdigit()
        if digit:
            run = run.lstrip("0") or "0"
            if previous_digit:
                key += "-"
        key += run
        previous_digit = digit
    return key


def display_id(name: str) -> str:
    """OpenNGC's compact names as people write them: NGC0292 → NGC 292, Cl399 → Cr 399."""
    match = re.fullmatch(r"([A-Za-z]+)(\d[\d-]*)(.*)", name)
    if match is None:
        return name
    prefix, number, rest = match.groups()
    prefix = {"Cl": "Cr"}.get(prefix, prefix)
    number = "-".join(part.lstrip("0") or "0" for part in number.split("-"))
    return f"{prefix} {number}{rest}"
