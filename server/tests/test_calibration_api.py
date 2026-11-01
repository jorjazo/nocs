# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The calibration library over the API (ADR 0036)."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api.app import create_app
from nocs.config import Settings
from nocs.storage.catalog import Catalog, NewFrame
from nocs.storage.volumes import Volumes

LIGHT = NewFrame(
    night=date(2026, 11, 1),
    site="Lab",
    target="NGC 253",
    volume="internal",
    volume_label="Internal",
    mount_point="/srv",
    directory=PurePosixPath(""),
    path=PurePosixPath("2026-11-01/Light/NGC_253/L/a.fits"),
    size=4,
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


def add(db: Catalog, data: Path, frame: NewFrame) -> int:
    """Saved on the internal destination, as storage would."""
    internal = Volumes().destination(data, internal=True)
    assert internal is not None
    frame = replace(
        frame,
        volume=internal.volume.id,
        volume_label=internal.volume.label,
        mount_point=str(internal.volume.mount.mount_point),
        directory=internal.relative,
    )
    file = data / "NOCS" / frame.path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"FITS")
    return db.add_frame(frame)


def test_the_library_of_a_night(tmp_path: Path) -> None:
    data = tmp_path / "data"
    settings = Settings(
        indi_host="127.0.0.1", indi_port=1, config_dir=tmp_path / "config", data_dir=data
    )
    data.mkdir()
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        db = Catalog(data / "catalog.sqlite")
        for i in range(3):
            add(
                db, data, replace(LIGHT, path=PurePosixPath(f"2026-11-01/Light/NGC_253/L/{i}.fits"))
            )
        # Darks from an earlier night, and the night's own flats.
        old = datetime(2026, 10, 2, 12, tzinfo=UTC)
        for i in range(2):
            add(
                db,
                data,
                replace(
                    LIGHT,
                    night=date(2026, 10, 2),
                    target=None,
                    frame_type="dark",
                    filter=None,
                    started=old,
                    temperature=-10.5,
                    path=PurePosixPath(f"2026-10-02/Dark/{i}.fits"),
                ),
            )
        add(
            db,
            data,
            replace(
                LIGHT,
                target=None,
                frame_type="flat",
                exposure=2,
                path=PurePosixPath("2026-11-01/Flat/L/0.fits"),
            ),
        )
        night = next(n for n in client.get("/api/nights").json() if n["night"] == "2026-11-01")

        response = client.get("/api/calibration", params={"night": night["id"], "darks": 5})
        assert response.status_code == 200, response.text
        report = response.json()
        [group] = report["groups"]
        assert (group["filter"], group["exposure"], group["lights"]) == ("L", 120, 3)
        assert (group["darks"]["frames"], group["darks"]["nights"]) == (2, ["2026-10-02"])
        assert group["flats"]["frames"] == 1
        assert group["flat_calibration"]["frames"] == 0
        assert [(n["kind"], n["count"]) for n in report["needs"]] == [
            ("bias", 50),
            ("dark", 3),
            ("flat", 19),
        ]
        assert report["frames"] == 3

        zipped = client.get(f"/api/nights/{night['id']}/zip", params={"calibration": True})
        assert zipped.status_code == 200, zipped.text
        names = sorted(zipfile.ZipFile(io.BytesIO(zipped.content)).namelist())
        assert names == [
            "2026-10-02/Dark/0.fits",
            "2026-10-02/Dark/1.fits",
            "2026-11-01/Flat/L/0.fits",
            *(f"2026-11-01/Light/NGC_253/L/{i}.fits" for i in range(3)),
        ]

        assert client.get("/api/calibration").status_code == 422
        assert client.get("/api/calibration", params={"night": 99}).status_code == 404
        response = client.get("/api/calibration", params={"sequence": "none"})
        assert response.status_code == 404
        # No profile: no site for the twilight, no camera for flats or darks.
        assert client.get("/api/flats/window").status_code == 409
        response = client.post("/api/flats", json={"filters": [{"filter": "L"}]})
        assert response.status_code == 503, response.text
        response = client.post("/api/calibration/sequence", json={"night": night["id"]})
        assert response.status_code == 409, response.text
