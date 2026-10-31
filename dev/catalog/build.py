"""Build the target catalog nocsd bundles from a pinned OpenNGC release (ADR 0019).

    uv run --project server python dev/catalog/build.py [--tarball openngc.tar.gz]

Downloads the release (or reads the given copy of it), checks its SHA-256, merges
NOCS's own names (dev/catalog/names.tsv) and writes server/src/nocs/targets/data/:
the catalog (gzipped JSON, byte for byte the same on every run) and OpenNGC's
licence. Commit both. To move to a new release, change VERSION and SHA256 and
check the result's counts and the search tests.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

from nocs.targets.catalog import DATA_FILE, FORMAT
from nocs.targets.openngc import build

VERSION = "v20260501"
SHA256 = "b10c86c2008f51f4fe653face1923390431894930ef23d381c2d1e8075d04265"
URL = f"https://github.com/mattiaverga/OpenNGC/archive/refs/tags/{VERSION}.tar.gz"

REPO = Path(__file__).resolve().parents[2]
NAMES = REPO / "dev" / "catalog" / "names.tsv"
OUT = REPO / "server" / "src" / "nocs" / "targets" / "data"

SOURCES = [
    {
        "name": "OpenNGC",
        "version": VERSION,
        "url": "https://github.com/mattiaverga/OpenNGC",
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution": (
            "Deep-sky objects from OpenNGC by Mattia Verga, CC BY-SA 4.0; "
            "converted, with common names added in English and Spanish, by NOCS."
        ),
    }
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the bundled target catalog from OpenNGC.")
    parser.add_argument("--tarball", type=Path, help=f"a local copy of {URL}")
    args = parser.parse_args()

    if args.tarball:
        data = args.tarball.read_bytes()
    else:
        print(f"downloading {URL}", file=sys.stderr)
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        sys.exit(f"error: OpenNGC {VERSION} has SHA-256 {digest}, expected {SHA256}")

    files = _members(
        data, "database_files/NGC.csv", "database_files/addendum.csv", "LICENSES/CC-BY-SA-4.0.txt"
    )
    targets = build(
        [files["database_files/NGC.csv"], files["database_files/addendum.csv"]],
        NAMES.read_text(encoding="utf-8"),
    )
    document = {
        "format": FORMAT,
        "sources": SOURCES,
        "objects": [t.to_row() for t in targets],
    }
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / DATA_FILE).write_bytes(gzip.compress(text.encode(), compresslevel=9, mtime=0))
    (OUT / "LICENSE-OpenNGC.txt").write_text(files["LICENSES/CC-BY-SA-4.0.txt"], encoding="utf-8")

    named = sum(1 for t in targets if t.names)
    spanish = sum(1 for t in targets if t.names_es)
    size = (OUT / DATA_FILE).stat().st_size
    print(
        f"{len(targets)} objects ({named} with English names, {spanish} with Spanish ones), "
        f"{len(text.encode()) / 1e6:.2f} MB of JSON, {size / 1e3:.0f} kB gzipped: {OUT / DATA_FILE}"
    )


def _members(tarball: bytes, *paths: str) -> dict[str, str]:
    """Files from the release by their path below its top directory, read in memory."""
    found: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        for member in archive.getmembers():
            path = member.name.split("/", 1)[-1]
            if path in paths and member.isfile():
                extracted = archive.extractfile(member)
                assert extracted is not None
                found[path] = extracted.read().decode("utf-8")
    missing = set(paths) - found.keys()
    if missing:
        sys.exit(f"error: {', '.join(sorted(missing))} not in the release")
    return found


if __name__ == "__main__":
    main()
