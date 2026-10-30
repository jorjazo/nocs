"""Where a frame goes below ``<destination>/NOCS/`` and what it is called (ADR 0013)."""

from __future__ import annotations

import re
import string
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import PurePosixPath

ROOT = "NOCS"
UNTITLED = "Untitled"
TYPE_FOLDERS = {"light": "Light", "dark": "Dark", "flat": "Flat", "bias": "Bias"}

DEFAULT_TEMPLATE = "{datetime}_{type}_{filter}_{exposure}s_{temperature}C_{seq}"
FIELDS = frozenset(
    {
        "target",
        "night",
        "type",
        "filter",
        "exposure",
        "gain",
        "offset",
        "temperature",
        "binning",
        "camera",
        "datetime",
        "seq",
    }
)
MAX_NAME = 64
_FORBIDDEN = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


class TemplateError(ValueError):
    pass


def night_of(start: datetime, longitude: float | None) -> date:
    """The date at the start of the night an exposure belongs to; it changes at local noon.

    With a site longitude, local mean solar time (UTC + longitude / 15 h), which
    needs no time zone database; without one, the system time zone.
    """
    if longitude is not None:
        local = start.astimezone(UTC) + timedelta(hours=longitude / 15)
    else:
        local = start.astimezone()
    return (local - timedelta(hours=12)).date()


def clean(name: str) -> str:
    """A name usable as a folder or file name on any filesystem, FAT included.

    Letters and digits of any script and ``-_.+`` are kept; spaces become ``_``;
    anything else is dropped.
    """
    name = unicodedata.normalize("NFC", name.strip())
    kept = "".join(c if c.isalnum() or c in "-_.+" else "_" if c.isspace() else "" for c in name)
    kept = re.sub(r"_{2,}", "_", kept).strip("._")
    return kept[:MAX_NAME].rstrip("._")


def folder(frame_type: str, night: date, target: str | None, filter: str | None) -> PurePosixPath:
    """``<night>/Light/<target>/<filter>``, ``<night>/Flat/<filter>``, ``<night>/Dark``…"""
    path = PurePosixPath(night.isoformat(), TYPE_FOLDERS[frame_type])
    if frame_type == "light":
        path /= clean(target or "") or UNTITLED
    if frame_type in ("light", "flat") and filter and (name := clean(filter)):
        path /= name
    return path


def check_template(template: str) -> str:
    """Validate a file name template: known fields only, nothing a file name cannot hold."""
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as e:
        raise TemplateError(f"invalid template: {e}") from None
    fields = 0
    for literal, name, spec, conversion in parsed:
        if _FORBIDDEN.search(literal):
            raise TemplateError(f"the template has characters a file name cannot hold: {literal!r}")
        if name is None:
            continue
        if name not in FIELDS:
            raise TemplateError(f"unknown field {{{name}}}; use {', '.join(sorted(FIELDS))}")
        if spec or conversion:
            raise TemplateError(f"field {{{name}}} takes no format")
        fields += 1
    if not fields:
        raise TemplateError("the template needs at least one field")
    return template


@dataclass(frozen=True, slots=True)
class NameFields:
    target: str | None
    night: date
    frame_type: str
    filter: str | None
    exposure: float
    gain: float | None
    offset: float | None
    temperature: float | None
    binning: int | None
    camera: str
    start: datetime
    seq: int


def _number(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def file_stem(template: str, fields: NameFields) -> str:
    """The file name (without extension) from a template checked with ``check_template``."""
    values = {
        "target": clean(fields.target or ""),
        "night": fields.night.isoformat(),
        "type": TYPE_FOLDERS[fields.frame_type],
        "filter": clean(fields.filter or ""),
        "exposure": _number(fields.exposure),
        "gain": _number(fields.gain),
        "offset": _number(fields.offset),
        "temperature": "" if fields.temperature is None else f"{round(fields.temperature):d}",
        "binning": "" if fields.binning is None else f"{fields.binning}x{fields.binning}",
        "camera": clean(fields.camera),
        "datetime": f"{fields.start.astimezone(UTC):%Y%m%d-%H%M%S}",
        "seq": f"{fields.seq:04d}",
    }
    parts: list[str] = []
    empty = False
    for literal, name, _, _ in string.Formatter().parse(template):
        if empty:
            # A unit after an empty field ("{temperature}C") goes with it.
            literal = re.sub(r"^[^_\- .]+", "", literal)
        parts.append(literal)
        value = values[name] if name is not None else ""
        parts.append(value)
        empty = name is not None and not value
    stem = re.sub(r"_{2,}", "_", "".join(parts)).strip("_- .")
    return stem or "frame"
