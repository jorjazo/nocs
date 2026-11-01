"""Sessions: the runs of sequences the catalog keeps, and their reports (phase 5.15).

A report is built from the session's events: frame events carry the saved frame's
catalog id, failures under clouds the id of the frame they kept, autofocus actions
their result. Frames, temperatures and guiding come from the catalog.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import statistics
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, HTTPException, Query, Response, status

from nocs.api.schemas import (
    ReportFilter,
    ReportFocus,
    ReportFrame,
    SequenceEvent,
    SessionReport,
    SessionSummary,
    TemperatureRecord,
)
from nocs.storage import FrameRow, Session, SessionEvent, StorageError, StorageService

CSV_COLUMNS = (
    "id",
    "started",
    "type",
    "filter",
    "exposure",
    "stars",
    "hfr",
    "guide_rms",
    "temperature",
    "clouds",
)


def sessions_router(
    storage: Callable[[], StorageService], now: Callable[[], datetime]
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/sessions")
    async def sessions(  # pyright: ignore[reportUnusedFunction]
        before: int | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 20
    ) -> list[SessionSummary]:
        """Newest first."""
        with _errors():
            found = await anyio.to_thread.run_sync(storage().sessions, limit, before)
        return [summary(session) for session in found]

    @router.get("/sessions/{session_id}/report")
    async def report(session_id: int) -> SessionReport:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            return await anyio.to_thread.run_sync(build, storage(), session_id, now())

    @router.get("/sessions/{session_id}/frames.csv")
    async def frames_csv(session_id: int) -> Response:  # pyright: ignore[reportUnusedFunction]
        """The session's frames, one row each, for a spreadsheet or a stacking tool."""
        with _errors():
            found = await anyio.to_thread.run_sync(build, storage(), session_id, now())
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(CSV_COLUMNS)
        for frame in found.frames:
            writer.writerow(
                [
                    frame.id,
                    frame.started,
                    frame.frame_type,
                    frame.filter or "",
                    frame.exposure,
                    _blank(frame.stars),
                    _blank(frame.hfr),
                    _blank(frame.guide_rms),
                    _blank(frame.temperature),
                    "yes" if frame.clouds else "",
                ]
            )
        name = f"session-{session_id}-frames.csv"
        return Response(
            out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    return router


def summary(session: Session) -> SessionSummary:
    assert session.id is not None
    outcome = session.outcome if session.outcome in ("completed", "stopped", "failed") else None
    return SessionSummary(
        id=session.id,
        run=session.run,
        sequence=session.sequence,
        name=session.name,
        profile=session.profile,
        started=session.started,
        ended=session.ended,
        outcome=outcome,
        error=session.error,
        restarts=session.restarts,
    )


def build(storage: StorageService, session_id: int, now: datetime) -> SessionReport:
    """The report of a session; ``KeyError`` when the catalog has no such session."""
    found = storage.session(session_id)
    if found is None:
        raise KeyError(session_id)
    session, rows = found
    events = [_event(row) for row in rows]
    clouds: set[int] = set()
    ids: list[int] = []
    for event in events:
        if event.kind == "frame" and isinstance(frame_id := event.data.get("id"), int):
            ids.append(frame_id)
        elif event.kind == "failed" and isinstance(frame_id := event.data.get("frame"), int):
            ids.append(frame_id)
            clouds.add(frame_id)
    frames = [_frame(row, row.id in clouds) for row in storage.frames_by_id(ids)]
    started = datetime.fromisoformat(session.started)
    ended = datetime.fromisoformat(session.ended) if session.ended else now
    temperatures = storage.temperatures(session.started, session.ended)
    lights = [f for f in frames if f.frame_type == "light"]
    return SessionReport(
        session=summary(session),
        duration=max(0.0, (ended - started).total_seconds()),
        integration=sum(f.exposure for f in lights if not f.clouds),
        filters=_filters(lights),
        frames=frames,
        focus=_focus(events),
        temperatures=[
            TemperatureRecord(
                time=t.time,
                focuser=t.focuser,
                ambient=t.ambient,
                humidity=t.humidity,
                dew_point=t.dew_point,
            )
            for t in temperatures
        ],
        failures=sum(e.kind == "failed" for e in events),
        recoveries=sum(e.kind == "recovery" for e in events),
        events=events,
    )


def _event(row: SessionEvent) -> SequenceEvent:
    try:
        data = json.loads(row.data)
    except ValueError:
        data = {}
    return SequenceEvent.model_validate(
        {
            "time": row.time,
            "kind": row.kind,
            "message": row.message,
            "path": row.path,
            "data": data if isinstance(data, dict) else {},
        }
    )


def _frame(row: FrameRow, clouds: bool) -> ReportFrame:
    return ReportFrame(
        id=row.id,
        started=row.started,
        frame_type=row.frame_type,  # pyright: ignore[reportArgumentType]
        filter=row.filter,
        exposure=row.exposure,
        stars=row.stars,
        hfr=row.hfr,
        guide_rms=row.guide_rms_total,
        temperature=row.temperature,
        clouds=clouds,
        url=f"/api/frames/{row.id}/file",
    )


def _filters(lights: list[ReportFrame]) -> list[ReportFilter]:
    order: list[str | None] = []
    for frame in lights:
        if frame.filter not in order:
            order.append(frame.filter)
    result: list[ReportFilter] = []
    for name in order:
        mine = [f for f in lights if f.filter == name]
        good = [f for f in mine if not f.clouds]
        result.append(
            ReportFilter(
                filter=name,
                frames=len(good),
                integration=sum(f.exposure for f in good),
                clouds=len(mine) - len(good),
                hfr=_median([f.hfr for f in good]),
                guide_rms=_median([f.guide_rms for f in good]),
            )
        )
    return result


def _focus(events: list[SequenceEvent]) -> list[ReportFocus]:
    """Every autofocus run, with the trigger that asked for it (the event just before)."""
    runs: list[ReportFocus] = []
    reason: str | None = None
    for event in events:
        if event.kind == "trigger":
            reason = event.message.removeprefix("autofocus: ")
            continue
        if event.kind == "action" and event.message == "autofocus":
            data: dict[str, Any] = event.data
            runs.append(
                ReportFocus(
                    time=event.time,
                    reason=reason,
                    filter=data.get("filter") if isinstance(data.get("filter"), str) else None,
                    position=_number(data.get("position")),
                    hfr=_number(data.get("hfr")),
                    temperature=_number(data.get("temperature")),
                )
            )
        if event.kind != "failed":
            reason = None
    return runs


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _median(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return statistics.median(known) if known else None


def _blank(value: object) -> object:
    return "" if value is None else value


@contextlib.contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no session {e.args[0]!r}") from e
    except StorageError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
