"""Create benchmark FITS frames with the INDI CCD simulator and the GSC catalog.

Configures the simulator as the reference rig (ASI2600-like 6248x4176 sensor,
3.76 µm pixels, RedCat 51 at 250 mm), points the simulated mount at a few
targets, and saves one mono frame per target plus one Bayer (color) frame.
A manifest records where each frame was taken, so plate solving can be checked.

Also measures how long a full-size frame takes from "expose" to "received",
which includes the INDI BLOB transfer.

Usage: uv run --project server python dev/bench/make_samples.py --out <dir>
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from nocs.devices import Camera, FrameType, Mount
from nocs.indi import IndiClient

SENSOR = {"SIM_XRES": 6248, "SIM_YRES": 4176, "SIM_XSIZE": 3.76, "SIM_YSIZE": 3.76}
OPTICS = {"FOCAL_LENGTH": 250, "APERTURE": 51}
TARGETS = [
    ("smc", 0.877, -72.8),
    ("m42", 5.588, -5.39),
    ("m31", 0.712, 41.27),
]


async def main(host: str, port: int, out: Path, exposure: float) -> None:
    manifest: list[dict[str, object]] = []
    async with IndiClient(host, port) as client:
        mount = Mount(client, "Telescope Simulator")
        camera = Camera(client, "CCD Simulator")
        await mount.connect()
        await mount.unpark()
        await camera.connect()
        # Defined by the driver some time after connecting.
        for name in ("SIMULATOR_SETTINGS", "SCOPE_INFO", "SIM_TESTS"):
            await client.wait_for_property(camera.name, name, timeout=30)
        await client.send(camera.name, "SIMULATOR_SETTINGS", SENSOR)
        await client.send(camera.name, "SCOPE_INFO", OPTICS)
        await asyncio.sleep(1)
        width = SENSOR["SIM_XRES"] * SENSOR["SIM_XSIZE"] / 1000
        height = SENSOR["SIM_YRES"] * SENSOR["SIM_YSIZE"] / 1000
        fov = width / OPTICS["FOCAL_LENGTH"] * 57.2958
        fov_height = height / OPTICS["FOCAL_LENGTH"] * 57.2958

        for index, (name, ra, dec) in enumerate(TARGETS):
            bayer = index == len(TARGETS) - 1
            await client.send(camera.name, "SIM_TESTS", {"BAYER": bayer})
            await mount.goto(ra, dec)
            await asyncio.sleep(2)  # let the simulator follow the mount
            started = time.monotonic()
            frame = await camera.expose(exposure, frame_type=FrameType.LIGHT)
            elapsed = time.monotonic() - started
            filename = f"{name}{'_bayer' if bayer else ''}.fits"
            (out / filename).write_bytes(frame.data)
            entry = {
                "file": filename,
                "ra_hours": ra,
                "dec_deg": dec,
                "fov_deg": round(fov, 3),
                "fov_height_deg": round(fov_height, 3),
                "bayer": bayer,
                "bytes": len(frame.data),
                "expose_to_received_s": round(elapsed, 2),
                "exposure_s": exposure,
            }
            manifest.append(entry)
            print(json.dumps(entry))
        await client.send(camera.name, "SIM_TESTS", {"BAYER": False})

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--indi", default="127.0.0.1:7624")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--exposure", type=float, default=5.0)
    args = parser.parse_args()
    host, _, port = args.indi.rpartition(":")
    args.out.mkdir(parents=True, exist_ok=True)
    asyncio.run(main(host, int(port), args.out, args.exposure))
