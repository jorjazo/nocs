"""Export the wire schemas as one JSON Schema document.

``python -m nocs.api.schema`` prints it; the web client generates its TypeScript
types from the output (``pnpm gen:types`` in ``web/``).
"""

import json
from typing import Any, Literal

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from nocs.api.schemas import (
    AccessPointRequest,
    ActiveSiteRequest,
    Almanac,
    AppState,
    AuthStatus,
    AutoDewRequest,
    AutofocusRequest,
    AutofocusRun,
    CalibrationPlan,
    CalibrationReport,
    CalibrationSequence,
    CalibrationSequenceRequest,
    CameraSettingsRequest,
    CatalogMatch,
    CatalogObject,
    CatalogSource,
    CenterRequest,
    ClockReport,
    ClockRequest,
    ConnectRequest,
    CoolingRequest,
    DestinationRequest,
    DetectedPort,
    DetectPortRequest,
    DitherNowRequest,
    DitherRequest,
    Driver,
    EjectRequest,
    EquatorialGoto,
    ExposeRequest,
    FilterNamesRequest,
    FilterSelectRequest,
    FinderRequest,
    FlatWindows,
    FocusCalibrationRequest,
    FocuserBacklashRequest,
    FocuserMoveRequest,
    FrameRecord,
    FrameSaved,
    GpsSiteRequest,
    GuideRequest,
    GuideSteps,
    GuidingExposureRequest,
    GuidingLoopRequest,
    Health,
    Hello,
    HorizontalGoto,
    HostnameRequest,
    JobStarted,
    LoopRequest,
    MapsLink,
    MapsLinkRequest,
    MountMoveRequest,
    MountSiteRequest,
    NetworkForgetRequest,
    NetworkJoinRequest,
    NetworkModeRequest,
    NetworkSetupRequest,
    NightInfo,
    ObserverRequest,
    OutputRequest,
    PadRequest,
    PadStatusMessage,
    PairedDevice,
    PairRequest,
    PassphraseRequest,
    PatchMessage,
    PolarAlignRequest,
    SequenceEstimate,
    SequencePauseRequest,
    SequenceStopRequest,
    SerialPortInfo,
    SessionReport,
    SessionSummary,
    SetPropertyRequest,
    ShareRequest,
    ShutdownRequest,
    SiteCreated,
    SkyChart,
    SkyMatch,
    SkyPointing,
    SkyVisibility,
    SnapshotMessage,
    SolvedFrames,
    SolveRequest,
    StackSaved,
    StackSwitchRequest,
    StateSnapshot,
    TailscaleLogin,
    TailscalePairRequest,
    TargetRequest,
    TemperatureRecord,
    TemplateRequest,
    TrackingRequest,
    VideoRecordRequest,
    VideoRecordStarted,
    VideoSettingsRequest,
    WifiNetwork,
)
from nocs.calibration.flats import FlatPlan
from nocs.equipment import Profile
from nocs.plan import NightPlan
from nocs.sequence import Sequence
from nocs.sequence.model import Template
from nocs.sites import Site
from nocs.stacking.settings import StackLook

type Mode = Literal["validation", "serialization"]

# Requests are what clients send (validation); everything else is what they receive.
MODELS: list[tuple[type[BaseModel], Mode]] = [
    (Hello, "validation"),
    (SetPropertyRequest, "validation"),
    (ConnectRequest, "validation"),
    (DetectPortRequest, "validation"),
    (Profile, "validation"),
    (CameraSettingsRequest, "validation"),
    (CoolingRequest, "validation"),
    (ExposeRequest, "validation"),
    (LoopRequest, "validation"),
    (DestinationRequest, "validation"),
    (EjectRequest, "validation"),
    (NetworkJoinRequest, "validation"),
    (NetworkForgetRequest, "validation"),
    (AccessPointRequest, "validation"),
    (NetworkModeRequest, "validation"),
    (NetworkSetupRequest, "validation"),
    (ShareRequest, "validation"),
    (TargetRequest, "validation"),
    (TemplateRequest, "validation"),
    (EquatorialGoto, "validation"),
    (HorizontalGoto, "validation"),
    (TrackingRequest, "validation"),
    (OutputRequest, "validation"),
    (AutoDewRequest, "validation"),
    (MountSiteRequest, "validation"),
    (Site, "validation"),
    (ActiveSiteRequest, "validation"),
    (SiteCreated, "serialization"),
    (MapsLinkRequest, "validation"),
    (MapsLink, "serialization"),
    (GpsSiteRequest, "validation"),
    (ClockRequest, "validation"),
    (FocuserMoveRequest, "validation"),
    (FilterSelectRequest, "validation"),
    (FilterNamesRequest, "validation"),
    (AutofocusRequest, "validation"),
    (FocusCalibrationRequest, "validation"),
    (FocuserBacklashRequest, "validation"),
    (MountMoveRequest, "validation"),
    (StackSwitchRequest, "validation"),
    (VideoSettingsRequest, "validation"),
    (VideoRecordRequest, "validation"),
    (FrameSaved, "serialization"),
    (StackSaved, "serialization"),
    (StackLook, "validation"),
    (GuidingLoopRequest, "validation"),
    (GuidingExposureRequest, "validation"),
    (GuideRequest, "validation"),
    (DitherRequest, "validation"),
    (DitherNowRequest, "validation"),
    (Sequence, "validation"),
    (Template, "validation"),
    (NightPlan, "validation"),
    (SequenceEstimate, "serialization"),
    (SessionSummary, "serialization"),
    (SessionReport, "serialization"),
    (CalibrationReport, "serialization"),
    (CalibrationSequenceRequest, "validation"),
    (CalibrationPlan, "serialization"),
    (CalibrationSequence, "serialization"),
    (FlatPlan, "validation"),
    (FlatWindows, "serialization"),
    (SequencePauseRequest, "validation"),
    (SequenceStopRequest, "validation"),
    (GuideSteps, "serialization"),
    (AutofocusRun, "serialization"),
    (TemperatureRecord, "serialization"),
    (SolveRequest, "validation"),
    (CenterRequest, "validation"),
    (FinderRequest, "validation"),
    (PolarAlignRequest, "validation"),
    (ClockReport, "serialization"),
    (PadRequest, "validation"),
    (PadStatusMessage, "serialization"),
    (NightInfo, "serialization"),
    (Almanac, "serialization"),
    (SkyVisibility, "serialization"),
    (SkyMatch, "serialization"),
    (SkyPointing, "serialization"),
    (FrameRecord, "serialization"),
    (SolvedFrames, "serialization"),
    (PairRequest, "validation"),
    (TailscalePairRequest, "validation"),
    (TailscaleLogin, "serialization"),
    (PassphraseRequest, "validation"),
    (ObserverRequest, "validation"),
    (ShutdownRequest, "validation"),
    (HostnameRequest, "validation"),
    (AuthStatus, "serialization"),
    (PairedDevice, "serialization"),
    (JobStarted, "serialization"),
    (VideoRecordStarted, "serialization"),
    (Driver, "serialization"),
    (SerialPortInfo, "serialization"),
    (DetectedPort, "serialization"),
    (WifiNetwork, "serialization"),
    (CatalogObject, "serialization"),
    (CatalogMatch, "serialization"),
    (CatalogSource, "serialization"),
    (SkyChart, "serialization"),
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
