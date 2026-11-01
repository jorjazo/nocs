"""OpenNGC's CSV files turned into targets (run by ``dev/catalog/build.py``).

OpenNGC (https://github.com/mattiaverga/OpenNGC, CC BY-SA 4.0) lists every NGC and
IC object, plus an addendum of bright objects outside them (the Magellanic Clouds,
the Pleiades, some Caldwell and Melotte objects). Rows of type ``Dup`` repeat an
object under another designation; ``NonEx`` ones do not exist.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from nocs.targets.catalog import Target, TargetType
from nocs.targets.text import display_id

TYPES: dict[str, TargetType] = {
    "*": "star",
    "**": "double_star",
    "*Ass": "asterism",
    "OCl": "open_cluster",
    "GCl": "globular_cluster",
    "Cl+N": "cluster_nebula",
    "G": "galaxy",
    "GPair": "galaxy_pair",
    "GTrpl": "galaxy_triplet",
    "GGroup": "galaxy_group",
    "PN": "planetary_nebula",
    "HII": "hii_region",
    "DrkN": "dark_nebula",
    "EmN": "emission_nebula",
    "Neb": "nebula",
    "RfN": "reflection_nebula",
    "SNR": "supernova_remnant",
    "Nova": "nova",
    "Other": "other",
}
SKIPPED_TYPES = {"Dup", "NonEx"}

# Cross-identifications kept as aliases: catalogs people search by. The rest
# (2MASX, SDSS, MCG, IRAS, …) would only make the file bigger.
KEPT_IDENTIFIERS = {"C", "Mel", "Cl", "LBN", "PK", "PGC", "UGC", "ESO"}
_IDENTIFIER = re.compile(r"([A-Za-z]+) (\d[\d-]*)(.*)")


class OpenNgcError(ValueError):
    pass


@dataclass
class _Object:
    row: dict[str, str]
    aliases: list[str] = field(default_factory=list[str])
    names: list[str] = field(default_factory=list[str])
    names_es: list[str] = field(default_factory=list[str])

    def alias(self, designation: str, own_id: str) -> None:
        if designation != own_id and designation not in self.aliases:
            self.aliases.append(designation)


def read_rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def build(tables: Iterable[str], extra_names: str = "") -> list[Target]:
    """Targets from OpenNGC's tables (NGC.csv, addendum.csv) and NOCS's own names.

    ``extra_names`` is a TSV of ``<OpenNGC name>  <en|es>  <name>[, <name>…]``:
    English names OpenNGC lacks, and Spanish ones; they go before OpenNGC's.
    """
    rows = [row for text in tables for row in read_rows(text)]
    objects: dict[str, _Object] = {}
    messier: dict[str, str] = {}
    for row in rows:
        if row["Type"] in SKIPPED_TYPES:
            continue
        if row["Type"] not in TYPES:
            raise OpenNgcError(f"{row['Name']}: unknown type {row['Type']}")
        if not row["RA"] or not row["Dec"]:
            raise OpenNgcError(f"{row['Name']}: no coordinates")
        objects[row["Name"]] = _Object(row)
        if row["M"]:
            messier[row["M"].lstrip("0")] = row["Name"]

    def resolve(row: dict[str, str]) -> str | None:
        """The object a Dup row repeats."""
        candidates = [messier.get(m.strip().lstrip("0"), "") for m in row["M"].split(",")]
        candidates += [f"NGC{n.strip()}" for n in row["NGC"].split(",") if n.strip()]
        candidates += [f"IC{n.strip()}" for n in row["IC"].split(",") if n.strip()]
        return next((c for c in candidates if c in objects), None)

    for name, obj in objects.items():
        own = display_id(name)
        row = obj.row
        if row["M"]:
            obj.alias(f"M {row['M'].lstrip('0')}", own)
        for identifier in _split(row["Identifiers"]):
            match = _IDENTIFIER.fullmatch(identifier)
            if match and match[1] == "C":
                obj.alias(display_id(identifier.replace(" ", "")), own)
        for catalog in ("NGC", "IC"):
            for number in _split(row[catalog]):
                obj.alias(display_id(f"{catalog}{number}"), own)
        for identifier in _split(row["Identifiers"]):
            match = _IDENTIFIER.fullmatch(identifier)
            if match and match[1] in KEPT_IDENTIFIERS and match[1] != "C":
                obj.alias(display_id(f"{match[1]}{match[2]}{match[3]}"), own)
        obj.names.extend(_split(row["Common names"]))

    duplicates: dict[str, str] = {}
    for row in rows:
        if row["Type"] == "Dup" and (target := resolve(row)) is not None:
            objects[target].alias(display_id(row["Name"]), display_id(target))
            duplicates[row["Name"]] = target
    _sort_messier_first(objects)

    for number, line in enumerate(extra_names.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            name, language, names = line.split("\t")
        except ValueError:
            raise OpenNgcError(
                f"names line {number}: expected three tab-separated fields"
            ) from None
        obj = objects.get(duplicates.get(name, name))
        if obj is None:
            raise OpenNgcError(f"names line {number}: {name} is not an object in OpenNGC")
        if language not in ("en", "es"):
            raise OpenNgcError(f"names line {number}: unknown language {language}")
        target_names = obj.names if language == "en" else obj.names_es
        # NOCS's names lead, in its order, also those OpenNGC has: clients show the
        # first, and OpenNGC's order put "Sculptor Filament" before NGC 253's usual name.
        own = _split(names)
        target_names[:] = [*own, *(n for n in target_names if n not in own)]

    return [_target(name, obj) for name, obj in objects.items()]


def _sort_messier_first(objects: dict[str, _Object]) -> None:
    for obj in objects.values():
        obj.aliases.sort(key=lambda a: not a.startswith("M "))


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _target(name: str, obj: _Object) -> Target:
    row = obj.row
    return Target(
        id=display_id(name),
        type=TYPES[row["Type"]],
        ra=round(_sexagesimal(row["RA"]), 7),
        dec=round(_sexagesimal(row["Dec"]), 6),
        constellation=row["Const"] or None,
        magnitude=_brightest(_number(row["V-Mag"]), _number(row["B-Mag"])),
        major_axis=_number(row["MajAx"]),
        minor_axis=_number(row["MinAx"]),
        position_angle=_number(row["PosAng"]),
        aliases=tuple(obj.aliases),
        names=tuple(obj.names),
        names_es=tuple(obj.names_es),
    )


def _sexagesimal(value: str) -> float:
    """``hh:mm:ss.ss`` or ``±dd:mm:ss.s`` as a decimal number."""
    sign = -1.0 if value.startswith("-") else 1.0
    parts = [float(p) for p in value.lstrip("+-").split(":")]
    return sign * (parts[0] + parts[1] / 60 + parts[2] / 3600)


def _number(value: str) -> float | None:
    return float(value) if value else None


def _brightest(*magnitudes: float | None) -> float | None:
    """The brightest magnitude given: V is almost always the brighter, but OpenNGC's
    is sometimes far off (11.1 for NGC 253, whose B is 7.9)."""
    return min((m for m in magnitudes if m is not None), default=None)
