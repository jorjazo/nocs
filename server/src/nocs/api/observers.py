"""What observers see of the state: all of it but the owner's location and networks
(ADR 0047).

Observer access (ADR 0014) also shares its view with any page the owner opens, rebound
to the box's address (ADR 0046). The rules below take out of snapshots and patches what
says where the box is or which networks it knows: the mount's and the saved sites'
coordinates, a GPS fix, the location drivers report, and Wi-Fi names. Positions that
follow from what is left (the mount's altitude and azimuth with its coordinates and the
time, tonight's sky) stay: observers watch the session through them.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from nocs.state.store import Json, Op, Patch, Path


class _Removed:
    """Marker for a node observers do not get at all."""


REMOVED = _Removed()

type Action = Callable[[Json], Json | _Removed]


def _remove(_: Json) -> _Removed:
    return REMOVED


def _none(_: Json) -> Json:
    return None


def _empty(_: Json) -> Json:
    return []


# Drivers' own words for where they are: INDI's telescope base class logs every new
# site ("Observer location updated: Latitude ... Longitude ..."), GPS drivers their fix.
_LOCATION_WORDS = re.compile(
    r"\b(lat|latitude|longitude|location|site|geographic|elevation|gps)\b", re.IGNORECASE
)


def _messages(value: Json) -> Json:
    if not isinstance(value, list):
        return value
    return [
        m
        for m in value
        if not (
            isinstance(m, dict)
            and isinstance(text := m.get("text"), str)
            and _LOCATION_WORDS.search(text)
        )
    ]


def _message(value: Json) -> Json:
    """A property's own message, which drivers may send with any update."""
    return None if isinstance(value, str) and _LOCATION_WORDS.search(value) else value


@dataclass(frozen=True, slots=True)
class Rule:
    """A node to hide: its path ("*" matches any key) and what observers get instead.

    ``fixed``: the action does not look at the node, so a change inside it becomes the
    replacement at the node (which also creates its parents, as the change does for the
    owner). Otherwise changes inside the node are dropped: the node must be set whole
    (the INDI messages), or be removed from a parent that exists before anything is set
    inside it (an INDI property is defined before it is updated)."""

    pattern: Path
    action: Action
    fixed: bool = True


RULES: tuple[Rule, ...] = (
    Rule(("sites",), _remove),
    Rule(("mount", "site"), _none),
    Rule(("gps", "latitude"), _none),
    Rule(("gps", "longitude"), _none),
    Rule(("gps", "elevation"), _none),
    Rule(("gps", "site"), _none),
    Rule(("network", "ssid"), _none),
    Rule(("network", "known"), _empty),
    Rule(("network", "joining"), _none),
    Rule(("network", "last_join"), _none),
    Rule(("indi", "devices", "*", "properties", "GEOGRAPHIC_COORD"), _remove),
    Rule(("indi", "devices", "*", "properties", "*", "message"), _message, fixed=False),
    Rule(("indi", "messages"), _messages, fixed=False),
)


def observer_state(state: dict[str, Json]) -> dict[str, Json]:
    """``state`` (a snapshot, not changed) as observers see it."""
    view: Json = state
    for rule in RULES:
        redacted = _redact(view, rule.pattern, rule.action)
        assert not isinstance(redacted, _Removed)  # patterns are never empty
        view = redacted
    assert isinstance(view, dict)
    return view


def observer_patch(patch: Patch) -> Patch:
    """``patch`` as observers see it: the same version, perhaps with fewer operations
    (none at all when it changed only what they do not see)."""
    return Patch(patch.version, tuple(_observer_ops(patch.ops)))


def _observer_ops(ops: tuple[Op, ...]) -> Iterator[Op]:
    for op in ops:
        seen: Op | None = op
        for rule in RULES:
            seen = _observer_op(seen, rule)
            if seen is None:
                break
        if seen is not None:
            yield seen


def _observer_op(op: Op, rule: Rule) -> Op | None:
    path, pattern = op.path, rule.pattern
    common = min(len(path), len(pattern))
    if not _matches(pattern[:common], path[:common]):
        return op  # elsewhere in the tree
    if len(path) > len(pattern):
        # Inside the hidden node: observers keep what they were given.
        replacement = rule.action(None) if rule.fixed else REMOVED
        if isinstance(replacement, _Removed):
            return None
        return Op("set", path[: len(pattern)], replacement)
    if len(path) == len(pattern):
        if op.op == "delete":
            return None if rule.action is _remove else op
        value = rule.action(op.value)
        return None if isinstance(value, _Removed) else Op("set", path, value)
    if op.op == "delete":
        return op  # a whole subtree goes, the hidden node with it
    value = _redact(op.value, pattern[len(path) :], rule.action)
    assert not isinstance(value, _Removed)
    return Op("set", path, value)


def _matches(pattern: Path, path: Path) -> bool:
    return all(p in ("*", key) for p, key in zip(pattern, path, strict=True))


def _redact(node: Json, rest: Path, action: Action) -> Json | _Removed:
    """``node`` with ``action`` applied below it at ``rest``; shares what it leaves."""
    if not rest:
        return action(node)
    if not isinstance(node, dict):
        return node
    first, tail = rest[0], rest[1:]
    keys = list(node) if first == "*" else [first] if first in node else []
    if not keys:
        return node
    out = dict(node)
    for key in keys:
        value = _redact(node[key], tail, action)
        if isinstance(value, _Removed):
            del out[key]
        else:
            out[key] = value
    return out
