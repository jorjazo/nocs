"""Benchmark ASTAP plate solving on the sample frames (standard library only).

For each frame in the manifest, solves twice with the ASTAP command-line solver:
"hinted" (mount position and field of view known, as when nocsd centers a
target) and "blind" (no position, as when the mount position is unknown).
Reports wall time, success, and the error against the known position.

Usage: python3 dev/bench/astap_bench.py <samples dir> --db <database dir>
       [--astap astap_cli] [--json out.json]
"""

import argparse
import json
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

TIMEOUT_S = 180


def parse_ini(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                values[key.strip()] = value.strip()
    return values


def separation_deg(ra1_h: float, dec1: float, ra2_h: float, dec2: float) -> float:
    a1, d1, a2, d2 = map(math.radians, (ra1_h * 15, dec1, ra2_h * 15, dec2))
    cos = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def solve(
    astap: str, db: Path, fits: Path, entry: dict[str, Any], hinted: bool, downsample: int
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / fits.name
        shutil.copy(fits, image)  # ASTAP writes .ini/.wcs next to the image
        cmd = [astap, "-f", str(image), "-d", str(db), "-z", str(downsample)]
        if hinted:
            cmd += [
                "-ra",
                str(entry["ra_hours"]),
                "-spd",
                str(entry["dec_deg"] + 90),
                "-fov",
                str(entry["fov_height_deg"]),
                "-r",
                "10",
            ]
        else:
            cmd += ["-r", "180", "-fov", "0"]
        start = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            returncode = None
        elapsed = time.perf_counter() - start
        ini = parse_ini(image.with_suffix(".ini"))
    result: dict[str, Any] = {
        "mode": ("hinted" if hinted else "blind") + f" z{downsample}",
        "seconds": round(elapsed, 2),
        "returncode": returncode,
        "solved": ini.get("PLTSOLVD") == "T",
    }
    if result["solved"]:
        ra = float(ini["CRVAL1"]) / 15
        dec = float(ini["CRVAL2"])
        result["error_arcmin"] = round(
            separation_deg(ra, dec, entry["ra_hours"], entry["dec_deg"]) * 60, 2
        )
        result["scale_arcsec_px"] = round(abs(float(ini.get("CDELT1", "nan"))) * 3600, 3)
    elif "WARNING" in ini or "ERROR" in ini:
        result["message"] = ini.get("ERROR") or ini.get("WARNING")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("samples", type=Path)
    parser.add_argument("--db", type=Path, required=True, help="directory with the star database")
    parser.add_argument("--astap", default="astap_cli")
    # The simulator renders very sharp stars (HFR < 1 px) that ASTAP's automatic 2x2
    # downsampling (-z 0) wipes out; real frames usually solve faster downsampled.
    parser.add_argument("--downsample", type=int, default=1, help="ASTAP -z (0 = auto)")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if shutil.which(args.astap) is None and not Path(args.astap).exists():
        raise SystemExit(f"ASTAP not found: {args.astap}")

    manifest = json.loads((args.samples / "manifest.json").read_text())
    results: list[dict[str, Any]] = []
    for entry in manifest:
        for hinted in (True, False):
            r = {"file": entry["file"]} | solve(
                args.astap, args.db, args.samples / entry["file"], entry, hinted, args.downsample
            )
            results.append(r)
            print(json.dumps(r))
    if args.json:
        args.json.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
