"""INDI XML wire protocol: incremental stream parsing and client message encoding.

The server sends an endless sequence of top-level XML elements with no enclosing
root. ``StreamParser`` wraps them in a synthetic root and yields one message per
complete top-level element, discarding it afterwards so memory stays bounded
even with large BLOBs.
"""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from nocs.indi.properties import (
    BlobElement,
    Element,
    LightElement,
    NumberElement,
    Permission,
    Property,
    PropertyState,
    PropertyType,
    SwitchElement,
    SwitchRule,
    TextElement,
)

PROTOCOL_VERSION = "1.7"

_TYPE_NAMES: dict[str, PropertyType] = {
    "Text": PropertyType.TEXT,
    "Number": PropertyType.NUMBER,
    "Switch": PropertyType.SWITCH,
    "Light": PropertyType.LIGHT,
    "BLOB": PropertyType.BLOB,
}
_DEF_TAGS = {f"def{n}Vector": t for n, t in _TYPE_NAMES.items()}
_SET_TAGS = {f"set{n}Vector": t for n, t in _TYPE_NAMES.items()}
_NEW_TAGS = {t: (f"new{n}Vector", f"one{n}") for n, t in _TYPE_NAMES.items()}


class BlobMode(StrEnum):
    NEVER = "Never"
    ALSO = "Also"
    ONLY = "Only"


@dataclass(frozen=True, slots=True)
class DefineProperty:
    property: Property


@dataclass(frozen=True, slots=True)
class ElementValue:
    text: str
    attrs: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SetProperty:
    device: str
    name: str
    type: PropertyType
    state: PropertyState | None
    timeout: float | None
    timestamp: str | None
    message: str | None
    values: Mapping[str, ElementValue]


@dataclass(frozen=True, slots=True)
class DeleteProperty:
    device: str
    name: str | None
    timestamp: str | None
    message: str | None


@dataclass(frozen=True, slots=True)
class Message:
    device: str | None
    timestamp: str | None
    message: str


type IndiMessage = DefineProperty | SetProperty | DeleteProperty | Message


class ProtocolError(Exception):
    pass


_SEXAGESIMAL_SPLIT = re.compile(r"[:\s]+")


def parse_number(text: str) -> float:
    """Parse an INDI number, which may be decimal or sexagesimal (``-12:30:15.5``)."""
    s = text.strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        pass
    parts = _SEXAGESIMAL_SPLIT.split(s)
    try:
        total = sum(abs(float(p)) / 60**i for i, p in enumerate(parts))
    except ValueError as e:
        raise ProtocolError(f"invalid number: {text!r}") from e
    return -total if parts[0].startswith("-") else total


def _opt_float(value: str | None) -> float | None:
    return parse_number(value) if value is not None else None


def _parse_define(elem: ET.Element, prop_type: PropertyType) -> DefineProperty:
    a = elem.attrib
    prop = Property(
        device=a["device"],
        name=a["name"],
        type=prop_type,
        label=a.get("label", a["name"]),
        group=a.get("group", ""),
        state=PropertyState(a.get("state", "Idle")),
        perm=Permission(a.get("perm", "ro")),
        rule=SwitchRule(a["rule"]) if "rule" in a else None,
        timeout=parse_number(a.get("timeout", "0")),
        timestamp=a.get("timestamp"),
        message=a.get("message"),
    )
    for child in elem:
        name = child.attrib["name"]
        label = child.attrib.get("label", name)
        text = child.text or ""
        element: Element
        match prop_type:
            case PropertyType.TEXT:
                element = TextElement(name, label, text.strip())
            case PropertyType.NUMBER:
                ca = child.attrib
                element = NumberElement(
                    name,
                    label,
                    parse_number(text),
                    format=ca.get("format", "%g"),
                    min=parse_number(ca.get("min", "0")),
                    max=parse_number(ca.get("max", "0")),
                    step=parse_number(ca.get("step", "0")),
                )
            case PropertyType.SWITCH:
                element = SwitchElement(name, label, text.strip() == "On")
            case PropertyType.LIGHT:
                element = LightElement(name, label, PropertyState(text.strip() or "Idle"))
            case PropertyType.BLOB:
                element = BlobElement(name, label)
        prop.elements[name] = element
    return DefineProperty(prop)


def _parse_set(elem: ET.Element, prop_type: PropertyType) -> SetProperty:
    a = elem.attrib
    return SetProperty(
        device=a["device"],
        name=a["name"],
        type=prop_type,
        state=PropertyState(a["state"]) if "state" in a else None,
        timeout=_opt_float(a.get("timeout")),
        timestamp=a.get("timestamp"),
        message=a.get("message"),
        values={
            child.attrib["name"]: ElementValue(child.text or "", dict(child.attrib))
            for child in elem
        },
    )


def parse_element(elem: ET.Element) -> IndiMessage | None:
    """Convert one complete top-level protocol element into a message.

    Returns ``None`` for elements a client does not need (e.g. ``getProperties``).
    """
    try:
        if (prop_type := _DEF_TAGS.get(elem.tag)) is not None:
            return _parse_define(elem, prop_type)
        if (prop_type := _SET_TAGS.get(elem.tag)) is not None:
            return _parse_set(elem, prop_type)
        a = elem.attrib
        if elem.tag == "delProperty":
            return DeleteProperty(a["device"], a.get("name"), a.get("timestamp"), a.get("message"))
        if elem.tag == "message":
            return Message(a.get("device"), a.get("timestamp"), a.get("message", ""))
    except (KeyError, ValueError) as e:
        raise ProtocolError(f"malformed <{elem.tag}>: {e}") from e
    return None


def decode_blob(text: str, fmt: str) -> bytes:
    data = base64.b64decode("".join(text.split()))
    if fmt.endswith(".z"):
        data = zlib.decompress(data)
    return data


def apply_set(prop: Property, msg: SetProperty) -> list[str]:
    """Apply a ``set*Vector`` update to a known property; return the changed element names."""
    if msg.state is not None:
        prop.state = msg.state
    if msg.timeout is not None:
        prop.timeout = msg.timeout
    if msg.timestamp is not None:
        prop.timestamp = msg.timestamp
    prop.message = msg.message
    changed: list[str] = []
    for name, update in msg.values.items():
        element = prop.elements.get(name)
        if element is None:
            continue
        match element:
            case TextElement():
                element.value = update.text.strip()
            case NumberElement():
                element.value = parse_number(update.text)
                for attr in ("min", "max", "step"):
                    if attr in update.attrs:
                        setattr(element, attr, parse_number(update.attrs[attr]))
                if "format" in update.attrs:
                    element.format = update.attrs["format"]
            case SwitchElement():
                element.value = update.text.strip() == "On"
            case LightElement():
                element.value = PropertyState(update.text.strip() or "Idle")
            case BlobElement():
                element.format = update.attrs.get("format", "")
                element.size = int(update.attrs.get("size", "0"))
                element.data = decode_blob(update.text, element.format)
        changed.append(name)
    return changed


class StreamParser:
    """Incremental parser for the server-to-client INDI stream."""

    def __init__(self) -> None:
        self._parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(events=("start", "end"))
        self._parser.feed(b"<indi>")
        self._root: ET.Element | None = None
        self._depth = 0

    def feed(self, data: bytes) -> list[IndiMessage]:
        try:
            self._parser.feed(data)
            # Expat >= 2.6 may defer parsing of a small trailing chunk ("reparse
            # deferral"); flush so a message is delivered as soon as it is complete.
            self._parser.flush()
            events = [cast(tuple[str, ET.Element], e) for e in self._parser.read_events()]
        except ET.ParseError as e:
            raise ProtocolError(f"invalid XML from server: {e}") from e
        messages: list[IndiMessage] = []
        for event, elem in events:
            if event == "start":
                if self._root is None:
                    self._root = elem
                self._depth += 1
                continue
            self._depth -= 1
            if self._depth == 1 and self._root is not None:
                if (msg := parse_element(elem)) is not None:
                    messages.append(msg)
                self._root.remove(elem)
        return messages


def _serialize(elem: ET.Element) -> bytes:
    return ET.tostring(elem, encoding="unicode").encode() + b"\n"


def encode_get_properties(device: str | None = None, name: str | None = None) -> bytes:
    elem = ET.Element("getProperties", version=PROTOCOL_VERSION)
    if device is not None:
        elem.set("device", device)
    if name is not None:
        elem.set("name", name)
    return _serialize(elem)


def _format_value(prop_type: PropertyType, value: str | float | bool) -> str:
    match prop_type:
        case PropertyType.SWITCH:
            return "On" if value else "Off"
        case PropertyType.NUMBER:
            return repr(float(value))
        case PropertyType.TEXT:
            return str(value)
        case _:
            raise ValueError(f"clients cannot send {prop_type} vectors")


def encode_new_vector(
    prop_type: PropertyType,
    device: str,
    name: str,
    values: Mapping[str, str | float | bool],
) -> bytes:
    vector_tag, element_tag = _NEW_TAGS[prop_type]
    elem = ET.Element(vector_tag, device=device, name=name)
    for element_name, value in values.items():
        child = ET.SubElement(elem, element_tag, name=element_name)
        child.text = _format_value(prop_type, value)
    return _serialize(elem)


def encode_enable_blob(device: str, mode: BlobMode, name: str | None = None) -> bytes:
    elem = ET.Element("enableBLOB", device=device)
    if name is not None:
        elem.set("name", name)
    elem.text = mode.value
    return _serialize(elem)
