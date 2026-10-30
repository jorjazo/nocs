"""How much receiving a full frame costs nocsd's event loop, by transfer mode.

For each mode, takes a few exposures with a real (or simulated) camera while a
probe task measures event-loop lag (how late a 10 ms sleep wakes up):

- ``blob``: the image arrives as a BLOB on a connection of its own (what nocsd
  does): base64 inside XML, parsed on the event loop.
- ``local``: the driver writes the FITS itself (``UPLOAD_LOCAL``) and only sends
  its path; possible when indiserver and nocsd share a filesystem.

Run it while nothing else uses the camera:

    uv run --project server python dev/bench/blob_bench.py --camera "ZWO CCD ASI2600MC Duo"
"""

import argparse
import asyncio
import json
import os
import statistics
import tempfile
import time

from nocs.devices import Camera
from nocs.imaging import image_connector
from nocs.indi import IndiClient


class LagProbe:
    def __init__(self, period: float = 0.01) -> None:
        self.period = period
        self.samples: list[float] = []

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            start = loop.time()
            await asyncio.sleep(self.period)
            self.samples.append(loop.time() - start - self.period)

    def take(self) -> list[float]:
        samples, self.samples = self.samples, []
        return samples


def file_path(client: IndiClient, camera: str) -> str | None:
    prop = client.get_property(camera, "CCD_FILE_PATH")
    return prop.text("FILE_PATH") if prop is not None else None


async def wait_for_new_path(
    client: IndiClient, camera: str, old: str | None, timeout: float
) -> str:
    """The driver reports each saved file's path in CCD_FILE_PATH; names never repeat."""
    await client.wait_for(lambda c: file_path(c, camera) not in (None, old), timeout)
    path = file_path(client, camera)
    assert path is not None
    return path


async def bench(args: argparse.Namespace) -> dict[str, object]:
    probe = LagProbe()
    probe_task = asyncio.create_task(probe.run())
    results: dict[str, object] = {}
    async with IndiClient(args.host, args.port) as client:
        await Camera(client, args.camera).connect()
        images = await image_connector(args.host, args.port)(args.camera)
        camera = Camera(client, args.camera, images)
        try:
            for mode in args.modes:
                runs: list[dict[str, float]] = []
                if mode == "local":
                    directory = tempfile.mkdtemp(prefix="nocs-blob-bench-")
                    await camera.command(
                        "UPLOAD_SETTINGS", {"UPLOAD_DIR": directory, "UPLOAD_PREFIX": "IMAGE_XXX"}
                    )
                    await camera.command(
                        "UPLOAD_MODE",
                        {"UPLOAD_CLIENT": False, "UPLOAD_LOCAL": True, "UPLOAD_BOTH": False},
                    )
                for _ in range(args.repeat):
                    probe.take()
                    start = time.monotonic()
                    if mode == "blob":
                        frame = await camera.expose(args.exposure)
                        size = len(frame.data)
                    else:
                        old = file_path(client, args.camera)
                        await client.send(
                            args.camera, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": args.exposure}
                        )
                        path = await wait_for_new_path(client, args.camera, old, args.exposure + 60)
                        size = await asyncio.to_thread(os.path.getsize, path)
                    total = time.monotonic() - start
                    lags = probe.take()
                    runs.append(
                        {
                            "total_s": round(total, 3),
                            "after_exposure_s": round(total - args.exposure, 3),
                            "size_mb": round(size / 1e6, 1),
                            "lag_max_ms": round(max(lags) * 1000, 1),
                            "lag_p99_ms": round(sorted(lags)[int(len(lags) * 0.99) - 1] * 1000, 1),
                        }
                    )
                    print(mode, runs[-1], flush=True)
                if mode == "local":
                    await camera.command(
                        "UPLOAD_MODE",
                        {"UPLOAD_CLIENT": True, "UPLOAD_LOCAL": False, "UPLOAD_BOTH": False},
                    )
                results[mode] = {
                    "runs": runs,
                    "median_after_exposure_s": statistics.median(
                        r["after_exposure_s"] for r in runs
                    ),
                    "median_lag_max_ms": statistics.median(r["lag_max_ms"] for r in runs),
                }
        finally:
            await images.close()
            probe_task.cancel()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=7624)
    parser.add_argument("--camera", default="CCD Simulator")
    parser.add_argument("--exposure", type=float, default=1.0)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--modes", nargs="+", default=["blob", "local"], choices=["blob", "local"])
    args = parser.parse_args()
    print(json.dumps(asyncio.run(bench(args)), indent=2))


if __name__ == "__main__":
    main()
