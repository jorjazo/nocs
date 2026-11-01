"""The calibration library for a night or a planned sequence (ADR 0036).

Blocking methods read the catalog: call them from a thread.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from nocs.calibration.darks import SEQUENCE_ID, darks_sequence
from nocs.calibration.library import Light, Need, Report, Setup, Wanted, lights_of, report
from nocs.equipment import Role
from nocs.imaging import CameraNotReadyError, CaptureService
from nocs.sequence import Sequence
from nocs.sequence.model import plans
from nocs.storage import FrameFilter, Located, NightRow, StorageService
from nocs.storage.layout import night_of


class CalibrationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CameraFacts:
    """What a planned sequence's lights will be taken with, from the camera now."""

    name: str
    width: int
    height: int
    binning: int
    gain: float | None
    offset: float | None
    min_exposure: float | None = None


BIAS_EXPOSURE = 0.001
"""Seconds, when the driver does not say its shortest."""


class CalibrationService:
    def __init__(
        self,
        storage: Callable[[], StorageService],
        sequence: Callable[[str], Sequence | None],
        put: Callable[[str, Sequence], None],
        camera: Callable[[], CameraFacts | None],
        now: Callable[[], datetime],
        longitude: Callable[[], float | None],
    ) -> None:
        self._storage = storage
        self._sequence = sequence
        self._put = put
        self._camera = camera
        self._now = now
        self._longitude = longitude

    def for_night(self, night_id: int, wanted: Wanted) -> tuple[NightRow, Report]:
        """Raises ``KeyError`` for an unknown night."""
        storage = self._storage()
        found = storage.nights(night_id)
        if not found:
            raise KeyError(night_id)
        rows = storage.frames(FrameFilter(night=night_id, frame_type="light"))
        lights = lights_of(f.row for f in rows)
        cameras = sorted({light.setup.camera for light in lights})
        return found[0], report(lights, storage.calibration_frames(cameras), wanted)

    def for_sequence(self, sequence_id: str, wanted: Wanted) -> Report:
        """Lights a saved sequence plans, as the camera would take them tonight."""
        sequence = self._sequence(sequence_id)
        if sequence is None:
            raise KeyError(sequence_id)
        camera = self._camera()
        if camera is None:
            raise CalibrationError("connect the main camera to see what the sequence needs")
        night = night_of(self._now(), self._longitude())
        cooling = sequence.template.cooling if sequence.template is not None else None
        lights: list[Light] = []
        for _, plan, _ in plans(sequence):
            if plan.frame_type != "light":
                continue
            for row in plan.rows:
                binning = row.binning or camera.binning
                setup = Setup(
                    camera.name,
                    camera.width // binning,
                    camera.height // binning,
                    binning,
                    row.gain if row.gain is not None else camera.gain,
                    row.offset if row.offset is not None else camera.offset,
                )
                lights.append(Light(setup, row.filter, row.exposure, cooling, night, row.count))
        storage = self._storage()
        cameras = [camera.name]
        return report(lights, storage.calibration_frames(cameras), wanted)

    def darks(
        self, night: int | None, sequence: str | None, wanted: Wanted, warm: bool
    ) -> tuple[Sequence, list[Need]]:
        """Keep the darks and bias missing for a night's or a sequence's lights as the
        ``calibration`` sequence; also what it could not include."""
        camera = self._camera()
        if camera is None:
            raise CalibrationError("connect the main camera to take darks and bias")
        if night is not None:
            row, found = self.for_night(night, wanted)
            name = f"Darks and bias for {row.night}"
        else:
            assert sequence is not None
            found = self.for_sequence(sequence, wanted)
            name = f"Darks and bias for {sequence}"
        built, left = darks_sequence(
            found.needs,
            camera=camera.name,
            sensor=(camera.width, camera.height),
            bias_exposure=camera.min_exposure
            if camera.min_exposure is not None and camera.min_exposure > 0
            else BIAS_EXPOSURE,
            warm=warm,
            name=name,
        )
        if not built.targets.children:
            raise CalibrationError("no darks or bias are missing")
        self._put(SEQUENCE_ID, built)
        return built, left

    def frames(self, night_id: int) -> list[Located]:
        """The calibration frames that match a night's lights, from any night."""
        _, found = self.for_night(night_id, Wanted())
        storage = self._storage()
        return storage.located(storage.frames_by_id(found.frames))


def camera_facts(capture: Callable[[], CaptureService]) -> Callable[[], CameraFacts | None]:
    """Reads the main camera through the capture service; ``None`` when not connected."""

    def read() -> CameraFacts | None:
        try:
            camera = capture().camera(Role.MAIN_CAMERA)
            sensor = camera.sensor
            return CameraFacts(
                camera.name,
                sensor.width,
                sensor.height,
                camera.binning[0],
                camera.gain,
                camera.offset,
            )
        except (CameraNotReadyError, KeyError, ValueError):
            return None

    return read
