"""Sequence definitions on disk: one JSON file per sequence in ``<config dir>/sequences/``.

Like profiles, they can be backed up, exported and edited by hand (ADR 0031).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from nocs.equipment.profiles import write_atomic
from nocs.sequence.model import SEQUENCE_ID, Sequence

log = logging.getLogger(__name__)


class SequenceError(Exception):
    pass


def check_id(sequence_id: str) -> str:
    if not SEQUENCE_ID.fullmatch(sequence_id):
        raise SequenceError(
            f"invalid sequence id {sequence_id!r}: use lower-case letters, digits and dashes"
        )
    return sequence_id


class SequenceStore:
    def __init__(self, config_dir: Path) -> None:
        self._dir = config_dir / "sequences"

    def load_all(self) -> dict[str, Sequence]:
        sequences: dict[str, Sequence] = {}
        if not self._dir.is_dir():
            return sequences
        for path in sorted(self._dir.glob("*.json")):
            if not SEQUENCE_ID.fullmatch(path.stem):
                continue
            try:
                sequences[path.stem] = Sequence.model_validate_json(path.read_bytes())
            except (OSError, ValidationError) as e:
                log.warning("ignoring unreadable sequence %s: %s", path, e)
        return sequences

    def get(self, sequence_id: str) -> Sequence | None:
        try:
            return Sequence.model_validate_json(self._path(sequence_id).read_bytes())
        except FileNotFoundError:
            return None

    def put(self, sequence_id: str, sequence: Sequence) -> None:
        data = json.dumps(sequence.model_dump(mode="json", exclude_none=True), indent=2) + "\n"
        write_atomic(self._path(sequence_id), data)

    def delete(self, sequence_id: str) -> bool:
        try:
            self._path(sequence_id).unlink()
        except FileNotFoundError:
            return False
        return True

    def _path(self, sequence_id: str) -> Path:
        return self._dir / f"{check_id(sequence_id)}.json"
