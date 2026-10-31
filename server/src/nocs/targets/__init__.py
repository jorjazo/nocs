"""Targets to point at: the bundled OpenNGC catalog and its search (ADR 0019)."""

from nocs.targets.catalog import (
    Match,
    Source,
    Target,
    TargetCatalog,
    TargetType,
    bundled_catalog,
    loaded_catalog,
)
from nocs.targets.text import display_id, fold, id_key

__all__ = [
    "Match",
    "Source",
    "Target",
    "TargetCatalog",
    "TargetType",
    "bundled_catalog",
    "display_id",
    "fold",
    "id_key",
    "loaded_catalog",
]
