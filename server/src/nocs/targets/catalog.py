"""The bundled target catalog: loaded once, searched in memory (ADR 0019)."""

from __future__ import annotations

import bisect
import gzip
import json
import math
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from typing import Literal, cast, get_args

from nocs.targets.text import fold, id_key

type TargetType = Literal[
    "star",
    "double_star",
    "asterism",
    "open_cluster",
    "globular_cluster",
    "cluster_nebula",
    "galaxy",
    "galaxy_pair",
    "galaxy_triplet",
    "galaxy_group",
    "planetary_nebula",
    "hii_region",
    "dark_nebula",
    "emission_nebula",
    "nebula",
    "reflection_nebula",
    "supernova_remnant",
    "nova",
    "other",
]
TARGET_TYPES: frozenset[str] = frozenset(get_args(TargetType.__value__))

FORMAT = 1
"""Version of the data file's layout; the build script writes it, the loader checks it."""

DATA_FILE = "openngc.json.gz"


@dataclass(frozen=True, slots=True)
class Target:
    id: str
    """The object's designation in its source, e.g. NGC 1976."""
    type: TargetType
    ra: float
    """J2000, hours."""
    dec: float
    """J2000, degrees."""
    constellation: str | None
    magnitude: float | None
    """The brighter of the visual and blue magnitudes."""
    major_axis: float | None
    """Arcminutes."""
    minor_axis: float | None
    position_angle: float | None
    """Degrees from north through east."""
    aliases: tuple[str, ...]
    """Other designations: Messier first, then Caldwell, NGC/IC and the rest."""
    names: tuple[str, ...]
    """Common names in English."""
    names_es: tuple[str, ...]
    """Common names in Spanish, where they differ from the English ones."""

    @property
    def label(self) -> str:
        """How people call it: its Messier number if it has one."""
        messier = next((a for a in self.aliases if a.startswith("M ")), None)
        return messier or self.id

    def to_row(self) -> list[object]:
        return [
            self.id,
            self.type,
            self.ra,
            self.dec,
            self.constellation,
            self.magnitude,
            self.major_axis,
            self.minor_axis,
            self.position_angle,
            list(self.aliases),
            list(self.names),
            list(self.names_es),
        ]

    @classmethod
    def from_row(cls, row: list[object]) -> Target:
        (id_, type_, ra, dec, const, mag, major, minor, pa, aliases, names, names_es) = row
        if type_ not in TARGET_TYPES:
            raise ValueError(f"{id_}: unknown type {type_}")
        return cls(
            id=cast(str, id_),
            type=cast(TargetType, type_),
            ra=cast(float, ra),
            dec=cast(float, dec),
            constellation=cast(str | None, const),
            magnitude=cast(float | None, mag),
            major_axis=cast(float | None, major),
            minor_axis=cast(float | None, minor),
            position_angle=cast(float | None, pa),
            aliases=tuple(cast(list[str], aliases)),
            names=tuple(cast(list[str], names)),
            names_es=tuple(cast(list[str], names_es)),
        )


@dataclass(frozen=True, slots=True)
class Source:
    """Where bundled data comes from, and the attribution its licence asks for."""

    name: str
    version: str
    url: str
    license: str
    license_url: str
    attribution: str


@dataclass(frozen=True, slots=True)
class Match:
    target: Target
    matched: str
    """The designation or name the query matched."""


# Ranks, best first. Ties go to the brighter object.
_EXACT_ID = 0
_EXACT = 1
_NAME_START = 2
_ID_START = 3
_NAME_WORDS = 4
_NAME_INSIDE = 5


class TargetCatalog:
    def __init__(self, targets: Iterable[Target], sources: Iterable[Source] = ()) -> None:
        self.targets = tuple(targets)
        self.sources = tuple(sources)
        self._by_key: dict[str, list[tuple[int, str, bool]]] = {}
        names: list[tuple[str, int, str]] = []
        for index, target in enumerate(self.targets):
            primary = {target.id, target.label}
            for designation in (target.id, *target.aliases):
                key = id_key(designation)
                if key is not None:
                    entry = (index, designation, designation in primary)
                    self._by_key.setdefault(key, []).append(entry)
            for name in (*target.names, *target.names_es):
                folded = fold(name)
                names.append((folded, index, name))
                if folded.startswith("the "):
                    names.append((folded.removeprefix("the "), index, name))
        self._keys = sorted(self._by_key)
        self._names = names
        self._by_dec = sorted(range(len(self.targets)), key=lambda i: self.targets[i].dec)
        self._decs = [self.targets[i].dec for i in self._by_dec]
        self._reach = max((_half_axis(t) for t in self.targets), default=0.0)

    @classmethod
    def load(cls) -> TargetCatalog:
        """The catalog bundled with nocsd."""
        data = resources.files("nocs.targets").joinpath("data", DATA_FILE).read_bytes()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> TargetCatalog:
        document = json.loads(gzip.decompress(data))
        if not isinstance(document, dict) or document.get("format") != FORMAT:  # pyright: ignore[reportUnknownMemberType]
            raise ValueError(f"not a target catalog of format {FORMAT}")
        content = cast(dict[str, list[object]], document)
        sources = [Source(**cast(dict[str, str], s)) for s in content["sources"]]
        rows = cast(list[list[object]], content["objects"])
        return cls((Target.from_row(row) for row in rows), sources)

    def get(self, designation: str) -> Target | None:
        """The object a designation names, written loosely ("m42", "NGC 0292")."""
        key = id_key(designation)
        entries = self._by_key.get(key) if key is not None else None
        if not entries:
            return None
        # A designation that is some object's own id wins over one that is an alias.
        return self.targets[min(entries, key=lambda e: not e[2])[0]]

    def near(self, ra: float, dec: float, radius: float) -> list[Target]:
        """Objects within `radius` degrees of a J2000 point (RA in hours), counting their
        extent: a large one whose centre is outside may still cover part of the circle."""
        band = radius + self._reach
        low = bisect.bisect_left(self._decs, dec - band)
        high = bisect.bisect_right(self._decs, dec + band)
        found: list[Target] = []
        for index in self._by_dec[low:high]:
            target = self.targets[index]
            if separation(ra, dec, target.ra, target.dec) <= radius + _half_axis(target):
                found.append(target)
        return found

    def search(self, query: str, limit: int = 20) -> list[Match]:
        """Objects whose designation or name matches the query, best first."""
        best: dict[int, tuple[int, int, str]] = {}

        def consider(index: int, rank: int, matched: str, detail: int = 0) -> None:
            current = best.get(index)
            # On a tie, the shortest name: "Nebulosa de Orión" over "Gran Nebulosa de Orión".
            if current is None or (rank, detail, len(matched)) < (*current[:2], len(current[2])):
                best[index] = (rank, detail, matched)

        key = id_key(query)
        if key is not None:
            for index, designation, primary in self._by_key.get(key, ()):
                consider(index, _EXACT_ID if primary else _EXACT, designation)
            position = bisect.bisect_right(self._keys, key)
            while position < len(self._keys) and self._keys[position].startswith(key):
                other = self._keys[position]
                position += 1
                for index, designation, _ in self._by_key[other]:
                    # Shorter designations first: NGC 29x before NGC 29xx.
                    consider(index, _ID_START, designation, len(other))

        folded = fold(query)
        if folded:
            words = folded.split()
            for name, index, original in self._names:
                if name == folded:
                    consider(index, _EXACT, original)
                elif name.startswith(folded):
                    consider(index, _NAME_START, original)
                elif all(any(w.startswith(q) for w in name.split()) for q in words):
                    consider(index, _NAME_WORDS, original)
                elif folded in name:
                    consider(index, _NAME_INSIDE, original)

        def order(item: tuple[int, tuple[int, int, str]]) -> tuple[int, int, float, str]:
            index, (rank, detail, _) = item
            magnitude = self.targets[index].magnitude
            return (rank, detail, 99.0 if magnitude is None else magnitude, self.targets[index].id)

        ranked = sorted(best.items(), key=order)[:limit]
        return [Match(self.targets[index], matched) for index, (_, _, matched) in ranked]


def _half_axis(target: Target) -> float:
    """Degrees."""
    return (target.major_axis or 0.0) / 120


def separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Degrees between two points, RA in hours."""
    d1, d2 = math.radians(dec1), math.radians(dec2)
    dra = math.radians((ra2 - ra1) * 15)
    # Haversine: exact for small angles, where the cosine formula loses digits.
    h = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin(dra / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h))))


_lock = threading.Lock()
_bundled: TargetCatalog | None = None


def bundled_catalog() -> TargetCatalog:
    """The bundled catalog, loaded on first use (blocking: call it from a thread)."""
    global _bundled
    with _lock:
        if _bundled is None:
            _bundled = TargetCatalog.load()
        return _bundled


def loaded_catalog() -> TargetCatalog | None:
    """The bundled catalog if it is loaded already."""
    return _bundled
