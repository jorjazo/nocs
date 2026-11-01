# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Session reports from the catalog (phase 5.15)."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api.app import create_app
from nocs.config import Settings
from nocs.storage.catalog import Catalog, NewFrame, Session, SessionEvent, TemperatureSample

FRAME = NewFrame(
    night=date(2026, 11, 1),
    site="Lab",
    target="NGC 253",
    volume="internal",
    volume_label="Internal",
    mount_point="/srv",
    directory=PurePosixPath(""),
    path=PurePosixPath("2026-11-01/Light/NGC_253/L/a.fits"),
    size=1000,
    started=datetime(2026, 11, 2, 1, 0, tzinfo=UTC),
    exposure=120,
    frame_type="light",
    filter="L",
    profile="lab",
    camera="CCD Simulator",
    gain=100,
    offset=10,
    binning=1,
    temperature=-10,
    width=100,
    height=100,
)


def seed(db: Catalog) -> int:
    """A night: three L frames (the second under a cloud), one R, two autofocus runs."""
    ids: list[int] = []
    for i, (filter, stars, hfr) in enumerate(
        [("L", 400, 2.0), ("L", 2, 3.0), ("L", 380, 2.2), ("R", 300, 2.4)]
    ):
        frame = db.add_frame(
            replace(
                FRAME,
                filter=filter,
                path=PurePosixPath(f"2026-11-01/Light/NGC_253/{filter}/{i}.fits"),
                started=datetime(2026, 11, 2, 1, 2 * i, tzinfo=UTC),
            )
        )
        db.set_metrics(frame, stars, hfr)
        ids.append(frame)
    session = db.start_session(
        Session(
            run="r1",
            sequence="ngc-253",
            name="NGC 253",
            profile="lab",
            started="2026-11-02T00:58:00+00:00",
            ended=None,
            outcome=None,
            error=None,
            restarts=0,
            definition="{}",
        )
    )

    def event(time: str, kind: str, message: str, data: dict[str, object]) -> SessionEvent:
        return SessionEvent(
            f"2026-11-02T{time}+00:00", kind, message, "targets.0", json.dumps(data)
        )

    db.add_session_events(
        session,
        [
            event("00:58:00", "started", "NGC 253", {}),
            event(
                "00:59:00",
                "action",
                "autofocus",
                {"position": 36600, "hfr": 1.9, "temperature": 12.0, "filter": "L"},
            ),
            event("01:00:00", "frame", "L 120 s 1/3", {"row": 0, "id": ids[0]}),
            event(
                "01:02:00",
                "failed",
                "2 stars, fewer than 100",
                {"kind": "clouds", "then": "retry", "frame": ids[1]},
            ),
            event("01:04:00", "frame", "L 120 s 2/3", {"row": 0, "id": ids[2]}),
            event("01:05:00", "trigger", "autofocus: filter R", {}),
            event(
                "01:05:30",
                "action",
                "autofocus",
                {"position": 36700, "hfr": 2.0, "temperature": 11.5, "filter": "R"},
            ),
            event("01:06:00", "frame", "R 120 s 1/1", {"row": 1, "id": ids[3]}),
            event("01:07:00", "recovery", "restarted the main_camera's driver", {}),
            event("01:08:00", "ended", "completed", {"error": None}),
        ],
    )
    db.end_session(session, "2026-11-02T01:08:00+00:00", "completed", None)
    db.add_temperature(TemperatureSample("2026-11-02T01:00:00+00:00", 12.0, 13.0, 50.0, 3.0))
    db.add_temperature(TemperatureSample("2026-11-02T03:00:00+00:00", 9.0, 10.0, 60.0, 2.0))
    return session


def test_the_report_of_a_session(tmp_path: Path) -> None:
    settings = Settings(
        indi_host="127.0.0.1",
        indi_port=1,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        assert client.get("/api/sessions").json() == []
        session = seed(Catalog(tmp_path / "data" / "catalog.sqlite"))

        [listed] = client.get("/api/sessions").json()
        assert (listed["id"], listed["outcome"], listed["name"]) == (
            session,
            "completed",
            "NGC 253",
        )

        response = client.get(f"/api/sessions/{session}/report")
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["duration"] == 600
        assert report["integration"] == 3 * 120  # the frame under the cloud left out
        assert [(f["filter"], f["frames"], f["clouds"], f["hfr"]) for f in report["filters"]] == [
            ("L", 2, 1, 2.1),
            ("R", 1, 0, 2.4),
        ]
        assert [f["clouds"] for f in report["frames"]] == [False, True, False, False]
        assert report["frames"][0]["url"].endswith("/file")
        assert [(f["reason"], f["filter"], f["position"]) for f in report["focus"]] == [
            (None, "L", 36600),
            ("filter R", "R", 36700),
        ]
        assert [t["time"][11:16] for t in report["temperatures"]] == ["01:00"]
        assert (report["failures"], report["recoveries"]) == (1, 1)
        assert len(report["events"]) == 10

        table = client.get(f"/api/sessions/{session}/frames.csv")
        assert table.headers["content-type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(table.text)))
        assert rows[0][:4] == ["id", "started", "type", "filter"]
        assert [r[-1] for r in rows[1:]] == ["", "yes", "", ""]

        assert client.get("/api/sessions/999/report").status_code == 404
