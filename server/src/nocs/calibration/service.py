"""The calibration library for a night or a planned sequence (ADR 0036).

Blocking methods read the catalog: call them from a thread.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime

from nocs.calibration.darks import (
    SEQUENCE_ID,
    dark_groups,
    darks_template,
    flat_groups,
    full_frame,
)
from nocs.calibration.library import Light, Need, Report, Setup, Wanted, lights_of, report
from nocs.equipment import Role
from nocs.imaging import CameraNotReadyError, CaptureService
from nocs.sequence import Sequence
from nocs.sequence.model import Group, Template, plans
from nocs.sequence.template import expand
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
        template = sequence.template
        planned: list[tuple[Group, float | None, str | None]] = []
        if template is not None:
            for group in template.groups:
                temperature = {
                    "off": None,
                    "global": template.temperature,
                    "group": group.temperature,
                }[template.cooling]
                planned.append((group, temperature, None))
        else:
            for _, plan, target in plans(sequence):
                for row in plan.rows:
                    group = Group(
                        frame_type=plan.frame_type,
                        filter=row.filter,
                        exposure=row.exposure,
                        count=row.count,
                        gain=row.gain,
                        offset=row.offset,
                        binning=row.binning,
                    )
                    planned.append((group, None, target.name if target is not None else None))
        lights: list[Light] = []
        for group, temperature, target in planned:
            if group.frame_type != "light" or group.exposure is None:
                continue
            binning = group.binning or camera.binning
            setup = Setup(
                camera.name,
                camera.width // binning,
                camera.height // binning,
                binning,
                group.gain if group.gain is not None else camera.gain,
                group.offset if group.offset is not None else camera.offset,
            )
            lights.append(
                Light(
                    setup,
                    group.filter,
                    group.exposure,
                    temperature,
                    night,
                    group.count,
                    target=target,
                )
            )
        storage = self._storage()
        cameras = [camera.name]
        return report(lights, storage.calibration_frames(cameras), wanted, choose=False)

    def plan(
        self,
        night: int | None,
        sequence: str | None,
        wanted: Wanted,
        warm: bool,
        groups: Collection[str] | None = None,
    ) -> tuple[Template | None, list[Need], Report]:
        """The darks and bias missing for a night's or a sequence's lights, for the dark
        groups chosen (``None``: those chosen by default), as groups not kept (None when
        none are missing); also what they cannot include, and the report they come from.
        Raises ``KeyError`` for an unknown night or sequence, ``CalibrationError`` for an
        unknown group.
        """
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
        try:
            needs = found.chosen_needs(groups)
        except KeyError as e:
            raise CalibrationError(f"the lights changed: no group {e.args[0]!r}") from e
        built, left = darks_template(
            needs,
            camera=camera.name,
            sensor=(camera.width, camera.height),
            warm=warm,
            name=name,
        )
        return built, left, found

    def darks(
        self,
        night: int | None,
        sequence: str | None,
        wanted: Wanted,
        warm: bool,
        groups: Collection[str] | None = None,
    ) -> tuple[Template, list[Need]]:
        """``plan``, kept as the ``calibration`` sequence."""
        built, left, _ = self.plan(night, sequence, wanted, warm, groups)
        if built is None:
            if groups is not None:
                raise CalibrationError("the chosen groups miss no darks or bias")
            raise CalibrationError("no darks or bias are missing")
        self._put(SEQUENCE_ID, expand(built))
        return built, left

    def missing(self, sequence: str, wanted: Wanted) -> list[Group]:
        """Groups for the flats, bias and darks a sequence's lights still lack: flats
        first (a panel, right after the lights), then the bias and darks."""
        camera = self._camera()
        if camera is None:
            raise CalibrationError("connect the main camera to see what the sequence needs")
        found = self.for_sequence(sequence, wanted)
        sensor = (camera.width, camera.height)
        needs = [n for n in found.chosen_needs(None) if n.setup.camera == camera.name]
        darks = [n for n in needs if n.kind != "flat" and full_frame(n, sensor)]
        flats = [n for n in found.needs if n.kind == "flat" and n.setup.camera == camera.name]
        wanted_groups = [*flat_groups(flats), *dark_groups(darks)]
        found_sequence = self._sequence(sequence)
        template = found_sequence.template if found_sequence is not None else None
        planned: list[Group] = []
        if template is not None:
            for group in template.groups:
                temperature = {
                    "off": None,
                    "global": template.temperature,
                    "group": group.temperature,
                }[template.cooling]
                planned.append(
                    group.model_copy(
                        update={
                            "gain": group.gain if group.gain is not None else camera.gain,
                            "offset": group.offset if group.offset is not None else camera.offset,
                            "binning": group.binning or camera.binning,
                            "temperature": temperature,
                        }
                    )
                )
        return _not_planned(wanted_groups, planned)

    def frames(self, night_id: int) -> list[Located]:
        """The calibration frames that match a night's lights, from any night."""
        _, found = self.for_night(night_id, Wanted())
        storage = self._storage()
        return storage.located(storage.frames_by_id(found.frames))


def _not_planned(wanted: list[Group], planned: list[Group]) -> list[Group]:
    """What is wanted less the frames the sequence already plans alike."""
    left: list[Group] = []
    taken: dict[int, int] = {}
    for group in wanted:
        count = group.count
        for i, other in enumerate(planned):
            if not _alike(group, other):
                continue
            used = min(count, other.count - taken.get(i, 0))
            taken[i] = taken.get(i, 0) + used
            count -= used
        if count > 0:
            left.append(group.model_copy(update={"count": count}))
    return left


def _alike(a: Group, b: Group) -> bool:
    keys = ("frame_type", "filter", "gain", "offset")
    if any(getattr(a, k) != getattr(b, k) for k in keys) or (a.binning or 1) != (b.binning or 1):
        return False
    if a.frame_type == "dark" and a.exposure != b.exposure:
        return False
    return a.frame_type == "flat" or a.temperature is None or a.temperature == b.temperature


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
