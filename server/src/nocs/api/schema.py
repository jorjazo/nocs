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
    AuthStatus,
    CameraSettingsRequest,
    ClockReport,
    ClockRequest,
    ConnectRequest,
    CoolingRequest,
    DestinationRequest,
    Driver,
    EquatorialGoto,
    ExposeRequest,
    FrameRecord,
    Health,
    Hello,
    HorizontalGoto,
    JobStarted,
    LoopRequest,
    MountSiteRequest,
    NightInfo,
    ObserverRequest,
    PadRequest,
    PadStatusMessage,
    PairedDevice,
    PairRequest,
    PassphraseRequest,
    PatchMessage,
    SerialPortInfo,
    SetPropertyRequest,
    SnapshotMessage,
    StateSnapshot,
    TargetRequest,
    TemplateRequest,
    TrackingRequest,
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
    (DestinationRequest, "validation"),
    (TargetRequest, "validation"),
    (TemplateRequest, "validation"),
    (EquatorialGoto, "validation"),
    (HorizontalGoto, "validation"),
    (TrackingRequest, "validation"),
    (MountSiteRequest, "validation"),
    (ClockRequest, "validation"),
    (ClockReport, "serialization"),
    (PadRequest, "validation"),
    (PadStatusMessage, "serialization"),
    (NightInfo, "serialization"),
    (FrameRecord, "serialization"),
    (PairRequest, "validation"),
    (PassphraseRequest, "validation"),
    (ObserverRequest, "validation"),
    (AuthStatus, "serialization"),
    (PairedDevice, "serialization"),
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
