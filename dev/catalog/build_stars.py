"""Build the stars the framing chart bundles from the Tycho-2 catalogue (ADR 0020).

    uv run --project server python dev/catalog/build_stars.py [--dir <copies of the files>]

Downloads Tycho-2 (CDS I/259: the main catalogue in 20 parts and supplement 1, about
160 MB) or reads the files from the given directory, checks each one's SHA-256, keeps
the stars down to MAGNITUDE and writes server/src/nocs/targets/data/: the stars (the
same bytes on every run) and a notice with their licence. Commit both.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import sys
import urllib.request
from pathlib import Path

from nocs.targets.catalog import Source
from nocs.targets.stars import DATA_FILE, Star, encode
from nocs.targets.tycho2 import parse_main, parse_supplement, select

MAGNITUDE = 10.0
"""Faintest V kept."""

# cdsarc.cds.unistra.fr serves the same files; its CfA mirror answered when CDS did not.
MIRRORS = [
    "https://cdsarc.cds.unistra.fr/ftp/I/259/",
    "https://vizier.cfa.harvard.edu/ftp/cats/I/259/",
]
VERSION = "I/259 (2000)"
FILES = {
    "suppl_1.dat.gz": "d256a9fc47259d506e4849b054e9392a62b2ed128e48ac6a25a3a60fcc317f0e",
    "tyc2.dat.00.gz": "1b224570fc6eb151984ce106fdf797728649d1ea77aaf3effd2d3444cfac6df6",
    "tyc2.dat.01.gz": "36221f4a5cdd9c5009d64299d2e6409f8d4cdf924321768780165bd3e2a2a99a",
    "tyc2.dat.02.gz": "e2ea4eeb7d204dde70ac54d172b1c429540c0d23d62ec0d7500561adc44cc57b",
    "tyc2.dat.03.gz": "29e0cb57cba7e1651455efcb528276b0c28e1fe83f47f8ebe963e48d8b180afb",
    "tyc2.dat.04.gz": "d04868329b470aa320f0fe5e9c525be619a7a228b364433e5f114f2178946d9b",
    "tyc2.dat.05.gz": "51f08772197dcf0cd26ff098c866036340b797f71ee04be22712517c10c73c4e",
    "tyc2.dat.06.gz": "f55503a66abce0e11d1a4ccbcde1f4c97a6e3e769de85e005f57ba963086ab03",
    "tyc2.dat.07.gz": "bc15b5b1f6308477360fbb93f6a98d9029601cab68973202be0f8764c127f524",
    "tyc2.dat.08.gz": "315ac34c678bc2e0f568b43b6b2d7c3d7c9cf9c089b51115d18b872864e50426",
    "tyc2.dat.09.gz": "d66c671fa29aad10bc5fd697f68c918bb774c1ffc3c7db9c20234895268390d5",
    "tyc2.dat.10.gz": "d86529df819ebdf3f4b8892510973ee10e1db06930814e014dd467193e740d52",
    "tyc2.dat.11.gz": "fc0c3203b3d2787da54c43d9963e363c8a3926576c383b101a15350a7ca23e9c",
    "tyc2.dat.12.gz": "68fd9d7e7353d52dea0de043cc62b45c04d234104eb05c063dc23ea7b6759576",
    "tyc2.dat.13.gz": "a08ecc092e6d134742c0f594c56c5c2e02b8fd5e76cffb1779877f2fcefac3fc",
    "tyc2.dat.14.gz": "2846e8cc489795a4d8160d2d5b64ff0e9a00598adba35a52a4f8ccf4c5e38b3e",
    "tyc2.dat.15.gz": "74784a3656382090a70d778820335f4a781509dbe3fcb9e92d18cf96b2c46c72",
    "tyc2.dat.16.gz": "320560e3d551cc40fa1f54ef7133709bf4bd45efa6688f808be7c09be5544a4d",
    "tyc2.dat.17.gz": "a8154e940aa0a0e8f31d91b4bd9fd56e6849da42cddb13c7dda772439b06991a",
    "tyc2.dat.18.gz": "5e951a1a51df7956f205b83cbfa5501d357c843640a253c1e6d3917bebe7d928",
    "tyc2.dat.19.gz": "f59605a38116f517a31a7dbdee3469c077658f2f40b8afe5da2aeb832eaee3dd",
}

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "server" / "src" / "nocs" / "targets" / "data"

LICENSE = "CC BY-NC 3.0 IGO"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc/3.0/igo/"
SOURCE = Source(
    name="Tycho-2",
    version=VERSION,
    url="https://cdsarc.cds.unistra.fr/viz-bin/cat/I/259",
    license=LICENSE,
    license_url=LICENSE_URL,
    attribution=(
        "Stars from the Tycho-2 Catalogue (Høg et al. 2000), Credit: ESA, CC BY-NC 3.0 IGO; "
        f"stars to V {MAGNITUDE:g} selected and converted by NOCS."
    ),
)
NOTICE = f"""\
Stars for the framing chart: a subset of the Tycho-2 Catalogue

    Høg E., Fabricius C., Makarov V.V., Urban S., Corbin T., Wycoff G., Bastian U.,
    Schwekendiek P., Wicenec A., "The Tycho-2 Catalogue of the 2.5 Million Brightest
    Stars", Astron. Astrophys. 355, L27 (2000). CDS catalogue I/259.

Credit: ESA. The Hipparcos and Tycho Catalogues are distributed by ESA under the
Creative Commons Attribution-NonCommercial 3.0 IGO licence (CC BY-NC 3.0 IGO):
{LICENSE_URL}legalcode

Changes made by NOCS: only the stars of the main catalogue and its supplement 1 down
to Johnson V {MAGNITUDE:g} are kept (V approximated from BT and VT as the catalogue's
ReadMe gives it), with their J2000 positions rounded to 0.0001 degree and magnitudes
to 0.05, in a binary format of NOCS's own; supplement 1 positions are moved from
J1991.25 to J2000 by their proper motions. The subset is distributed under the same
licence. It may not be used for commercial purposes; NOCS works without this file
(the chart then shows no stars), so a commercial distribution can leave it out.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the bundled star file from Tycho-2.")
    parser.add_argument("--dir", type=Path, help="local copies of the catalogue's files")
    args = parser.parse_args()

    stars: list[Star] = []
    for name, expected in FILES.items():
        data = _read(name, args.dir)
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected:
            sys.exit(f"error: {name} has SHA-256 {digest}, expected {expected}")
        parse = parse_supplement if name.startswith("suppl") else parse_main
        stars += (parse(line) for line in gzip.decompress(data).decode("ascii").splitlines())

    kept = select(stars, MAGNITUDE)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / DATA_FILE).write_bytes(encode(kept, [SOURCE], MAGNITUDE))
    (OUT / "LICENSE-Tycho2.txt").write_text(NOTICE, encoding="utf-8")
    size = (OUT / DATA_FILE).stat().st_size
    print(
        f"{len(kept)} of {len(stars)} stars to V {MAGNITUDE:g}, "
        f"{size / 1e3:.0f} kB: {OUT / DATA_FILE}"
    )


def _read(name: str, directory: Path | None) -> bytes:
    if directory is not None:
        return (directory / name).read_bytes()
    for mirror in MIRRORS:
        print(f"downloading {mirror}{name}", file=sys.stderr)
        try:
            with urllib.request.urlopen(mirror + name, timeout=120) as response:
                return response.read()
        except OSError as error:
            print(f"  {error}", file=sys.stderr)
    sys.exit(f"error: no mirror served {name}")


if __name__ == "__main__":
    main()
