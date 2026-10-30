"""Export the wire schemas as one JSON Schema document.

``python -m nocs.api.schema`` prints it; the web client generates its TypeScript
types from the output (``pnpm gen:types`` in ``web/``).
"""

import json
from typing import Any, Literal

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from nocs.api.schemas import (
    AppState,
    CameraSettingsRequest,
    ConnectRequest,
    CoolingRequest,
    Driver,
    ExposeRequest,
    Health,
    Hello,
    JobStarted,
    LoopRequest,
    PatchMessage,
    SerialPortInfo,
    SetPropertyRequest,
    SnapshotMessage,
    StateSnapshot,
)
from nocs.equipment import Profile

type Mode = Literal["validation", "serialization"]

# Requests are what clients send (validation); everything else is what they receive.
MODELS: list[tuple[type[BaseModel], Mode]] = [
    (Hello, "validation"),
    (SetPropertyRequest, "validation"),
    (ConnectRequest, "validation"),
    (Profile, "validation"),
    (CameraSettingsRequest, "validation"),
    (CoolingRequest, "validation"),
    (ExposeRequest, "validation"),
    (LoopRequest, "validation"),
    (JobStarted, "serialization"),
    (Driver, "serialization"),
    (SerialPortInfo, "serialization"),
    (SnapshotMessage, "serialization"),
    (PatchMessage, "serialization"),
    (Health, "serialization"),
    (StateSnapshot, "serialization"),
    (AppState, "serialization"),
]


def _drop_field_titles(node: Any) -> None:
    """Remove per-field titles, which code generators turn into noise type aliases."""
    if isinstance(node, dict):
        properties = node.get("properties")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(properties, dict):
            for field in properties.values():  # pyright: ignore[reportUnknownVariableType]
                if isinstance(field, dict):
                    field.pop("title", None)  # pyright: ignore[reportUnknownMemberType]
        for child in node.values():  # pyright: ignore[reportUnknownVariableType]
            _drop_field_titles(child)
    elif isinstance(node, list):
        for child in node:  # pyright: ignore[reportUnknownVariableType]
            _drop_field_titles(child)


def build() -> dict[str, Any]:
    _, schema = models_json_schema(MODELS, title="NOCS API")
    _drop_field_titles(schema)
    return schema


def main() -> None:
    print(json.dumps(build(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
