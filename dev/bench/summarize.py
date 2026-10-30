"""Summarize a results directory written by dev/bench/run.sh as Markdown."""

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def mib(text: str) -> float:
    match = re.match(r"([\d.]+)\s*([KMG]i?B)", text)
    if not match:
        return 0.0
    value, unit = float(match[1]), match[2]
    return (
        value * {"KiB": 1 / 1024, "KB": 1 / 1024, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}[unit]
    )


def main(out: Path) -> None:
    print(f"# Benchmark results: {out.name}\n")
    system = out / "system.txt"
    if system.exists():
        print("```\n" + system.read_text().strip() + "\n```\n")

    samples = (
        (out / "samples.log").read_text().splitlines() if (out / "samples.log").exists() else []
    )
    rows = [json.loads(line) for line in samples if line.startswith("{")]
    if rows:
        print("## Frame transfer (INDI simulator, 26 MP)\n")
        print("| frame | exposure | expose→received |\n|---|---|---|")
        for r in rows:
            print(f"| {r['file']} | {r['exposure_s']} s | {r['expose_to_received_s']} s |")
        print()

    preview = load(out / "preview.json")
    if preview:
        machine, threads = preview["machine"], preview["opencv_threads"]
        print(f"## Preview pipeline ({machine}, OpenCV threads {threads})\n")
        keys = [k for k in preview["files"][0] if k.endswith("_ms")]
        bayer_keys = [k for f in preview["files"] for k in f if k.endswith("_ms") and k not in keys]
        keys += list(dict.fromkeys(bayer_keys))
        print("| stage (median ms) | " + " | ".join(f["file"] for f in preview["files"]) + " |")
        print("|---|" + "---|" * len(preview["files"]))
        for key in keys:
            cells = [f"{f[key]:.0f}" if key in f else "—" for f in preview["files"]]
            print(f"| {key.removesuffix('_ms')} | " + " | ".join(cells) + " |")
        print(
            "| stars (full / bin2) | "
            + " | ".join(f"{f['stars_full']} / {f['stars_bin2']}" for f in preview["files"])
            + " |"
        )
        print()

    astap = load(out / "astap.json")
    if astap:
        print("## ASTAP\n")
        print("| frame | mode | solved | time | error |\n|---|---|---|---|---|")
        for r in astap:
            arcmin = "\u2032"
            error = f"{r['error_arcmin']}{arcmin}" if "error_arcmin" in r else r.get("message", "")
            print(f"| {r['file']} | {r['mode']} | {r['solved']} | {r['seconds']} s | {error} |")
        print()

    resources = out / "resources.csv"
    if resources.exists():
        print("## Resources while guiding\n")
        stats: dict[str, dict[str, float]] = {}
        loads: list[float] = []
        temps: list[float] = []
        with resources.open() as f:
            for row in csv.DictReader(f):
                s = stats.setdefault(
                    row["container"], {"cpu": 0.0, "mem": 0.0, "n": 0.0, "cpu_sum": 0.0}
                )
                cpu = float(row["cpu"].rstrip("%") or 0)
                s["cpu"] = max(s["cpu"], cpu)
                s["cpu_sum"] += cpu
                s["n"] += 1
                s["mem"] = max(s["mem"], mib(row["mem"].split("/")[0]))
                loads.append(float(row["loadavg"]))
                if row.get("temp_c"):
                    temps.append(float(row["temp_c"]))
        print("| container | CPU avg | CPU max | memory max |\n|---|---|---|---|")
        for name, s in sorted(stats.items()):
            average = s["cpu_sum"] / s["n"]
            print(f"| {name} | {average:.1f} % | {s['cpu']:.1f} % | {s['mem']:.0f} MiB |")
        if loads:
            print(f"\nLoad average: max {max(loads):.2f}")
        if temps:
            print(f"CPU temperature: {min(temps):.1f} to {max(temps):.1f} °C")
    guide = out / "guide.log"
    if guide.exists():
        lines = [line for line in guide.read_text().splitlines() if "settled" in line]
        if lines:
            print("\n```\n" + "\n".join(lines) + "\n```")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
