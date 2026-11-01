#!/usr/bin/env python3
"""Publish packages and images to the NOCS apt repository (ADR 0035).

    publish.py debs --suite testing:5 [--suite stable:3] <.deb>...
    publish.py image --keep 2 <image.img.xz> [its .sha256 and .manifest.txt]

The repository is a bucket (Cloudflare R2, through the S3 API) or, for tests, a
local directory (``--local <dir>``). Each suite's ``Packages`` files are its state:
a publish downloads them, never the packages, adds the new entries, keeps the newest
versions, uploads new packages first and the signed indices last, then deletes the
packages no suite names any more.

Environment: ``R2_ENDPOINT``, ``R2_BUCKET``, ``AWS_ACCESS_KEY_ID`` and
``AWS_SECRET_ACCESS_KEY`` for the bucket; ``APT_SIGNING_KEY``, an armoured private
OpenPGP key without a passphrase, to sign. Standard library only, plus ``dpkg``,
``gpg`` and the ``aws`` command line.
"""

from __future__ import annotations

import argparse
import functools
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

ARCHITECTURES = ("amd64", "arm64")
COMPONENT = "main"
ORIGIN = "NOCS"
KEYRING = Path(__file__).with_name("nocs-archive-keyring.asc")


# -- the bucket ----------------------------------------------------------------------


class Bucket:
    """The repository's files, in R2 or (for tests) a local directory."""

    def __init__(self, local: Path | None) -> None:
        self._local = local
        if local is None:
            self._endpoint = os.environ["R2_ENDPOINT"]
            self._bucket = os.environ["R2_BUCKET"]

    def list(self, prefix: str) -> list[str]:
        if self._local is not None:
            keys = (str(p.relative_to(self._local)) for p in self._local.rglob("*") if p.is_file())
            return sorted(key for key in keys if key.startswith(prefix))
        out = self._aws("s3", "ls", "--recursive", f"s3://{self._bucket}/{prefix}", check=False)
        # "2026-10-31 12:00:00   1234 pool/main/n/nocs/nocs_0.1.0_arm64.deb"
        return sorted(line.split(maxsplit=3)[3] for line in out.splitlines() if line.strip())

    def get(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._local is not None:
            shutil.copyfile(self._local / key, path)
        else:
            self._aws("s3", "cp", "--only-show-errors", f"s3://{self._bucket}/{key}", str(path))

    def put(self, path: Path, key: str) -> None:
        print(f"  put {key}")
        if self._local is not None:
            (self._local / key).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, self._local / key)
        else:
            self._aws("s3", "cp", "--only-show-errors", str(path), f"s3://{self._bucket}/{key}")

    def delete(self, key: str) -> None:
        print(f"  delete {key}")
        if self._local is not None:
            (self._local / key).unlink(missing_ok=True)
        else:
            self._aws("s3", "rm", "--only-show-errors", f"s3://{self._bucket}/{key}")

    def _aws(self, *args: str, check: bool = True) -> str:
        env = os.environ | {"AWS_DEFAULT_REGION": "auto"}
        result = subprocess.run(
            ["aws", "--endpoint-url", self._endpoint, *args],
            env=env, capture_output=True, text=True, check=False,
        )  # fmt: skip
        if check and result.returncode != 0:
            sys.exit(f"aws {' '.join(args)}: {result.stderr.strip()}")
        return result.stdout


# -- packages ------------------------------------------------------------------------


def compare(a: str, b: str) -> int:
    """Debian version order, as dpkg sees it."""
    if a == b:
        return 0
    lower = subprocess.run(["dpkg", "--compare-versions", a, "lt", b], check=False)
    return -1 if lower.returncode == 0 else 1


def parse_stanzas(text: str) -> list[dict[str, str]]:
    stanzas: list[dict[str, str]] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        fields: dict[str, str] = {}
        key = ""
        for line in block.splitlines():
            if line[:1] in (" ", "\t") and key:
                fields[key] += "\n" + line
            elif ":" in line:
                key, value = line.split(":", 1)
                fields[key] = value.strip()
        if fields:
            stanzas.append(fields)
    return stanzas


def format_stanza(fields: dict[str, str]) -> str:
    return "".join(f"{key}: {value}\n" for key, value in fields.items())


def stanza_for(deb: Path, filename: str) -> dict[str, str]:
    control = subprocess.run(
        ["dpkg-deb", "--field", str(deb)], capture_output=True, text=True, check=True
    ).stdout
    fields = parse_stanzas(control)[0]
    data = deb.read_bytes()
    fields |= {
        "Filename": filename,
        "Size": str(len(data)),
        "MD5sum": hashlib.md5(data).hexdigest(),
        "SHA1": hashlib.sha1(data).hexdigest(),
        "SHA256": hashlib.sha256(data).hexdigest(),
    }
    return fields


def pool_path(fields: dict[str, str], deb: Path) -> str:
    name = fields["Package"]
    return f"pool/{COMPONENT}/{name[0]}/{name}/{deb.name}"


def publish_debs(bucket: Bucket, suites: dict[str, int], debs: list[Path]) -> None:
    work = Path(tempfile.mkdtemp(prefix="nocs-repo-"))
    try:
        # Every suite's current entries, and what the pool holds.
        indices: dict[tuple[str, str], list[dict[str, str]]] = {}
        all_suites = {key.split("/")[1] for key in bucket.list("dists/") if key.count("/") > 2}
        for suite in sorted(all_suites | set(suites)):
            for arch in ARCHITECTURES:
                key = f"dists/{suite}/{COMPONENT}/binary-{arch}/Packages"
                if key in bucket.list(key):
                    bucket.get(key, work / key)
                    indices[suite, arch] = parse_stanzas((work / key).read_text())
                else:
                    indices[suite, arch] = []
        pool = [key for key in bucket.list("pool/") if key.endswith(".deb")]

        new: list[tuple[Path, dict[str, str]]] = []
        for deb in debs:
            fields = stanza_for(deb, "")
            fields["Filename"] = pool_path(fields, deb)
            new.append((deb, fields))
            for suite in suites:
                for arch in ARCHITECTURES:
                    if fields["Architecture"] not in (arch, "all"):
                        continue
                    entries = indices[suite, arch]
                    entries[:] = [e for e in entries if e["Filename"] != fields["Filename"]]
                    entries.append(fields)

        # Keep the newest `keep` versions of each package in each suite.
        for suite, keep in suites.items():
            for arch in ARCHITECTURES:
                by_name: dict[str, list[dict[str, str]]] = {}
                for entry in indices[suite, arch]:
                    by_name.setdefault(entry["Package"], []).append(entry)
                kept: list[dict[str, str]] = []
                for name in sorted(by_name):
                    ordered = sorted(
                        by_name[name],
                        key=functools.cmp_to_key(lambda a, b: compare(a["Version"], b["Version"])),
                    )
                    kept += ordered[-keep:]
                indices[suite, arch] = kept

        print("Uploading packages")
        for deb, fields in new:
            if fields["Filename"] not in pool:
                bucket.put(deb, fields["Filename"])

        print("Signing and uploading the indices")
        signer = Signer(work / "gnupg")
        for suite in suites:
            files = write_suite(work, suite, {a: indices[suite, a] for a in ARCHITECTURES})
            release = work / f"dists/{suite}/Release"
            signer.sign(release)
            for path in files:
                bucket.put(work / path, path)
            for name in ("Release", "Release.gpg", "InRelease"):
                bucket.put(work / f"dists/{suite}/{name}", f"dists/{suite}/{name}")
        if KEYRING.exists():
            bucket.put(KEYRING, KEYRING.name)

        named = {entry["Filename"] for entries in indices.values() for entry in entries}
        stale = [key for key in pool if key not in named]
        if stale:
            print("Deleting packages no suite names")
        for key in stale:
            bucket.delete(key)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_suite(work: Path, suite: str, indices: dict[str, list[dict[str, str]]]) -> list[str]:
    """Write a suite's Packages, Packages.gz and Release; return the indices' keys."""
    files: list[str] = []
    for arch, entries in indices.items():
        base = f"dists/{suite}/{COMPONENT}/binary-{arch}/Packages"
        text = "\n".join(format_stanza(e) for e in entries)
        (work / base).parent.mkdir(parents=True, exist_ok=True)
        (work / base).write_text(text)
        (work / f"{base}.gz").write_bytes(gzip.compress(text.encode(), mtime=0))
        files += [base, f"{base}.gz"]
    root = f"dists/{suite}/"
    lines = [
        f"Origin: {ORIGIN}",
        f"Label: {ORIGIN}",
        f"Suite: {suite}",
        f"Codename: {suite}",
        f"Date: {format_datetime(datetime.now(UTC), usegmt=True)}",
        f"Architectures: {' '.join(ARCHITECTURES)}",
        f"Components: {COMPONENT}",
        f"Description: NOCS packages ({suite})",
    ]
    for title, digest in (("MD5Sum", hashlib.md5), ("SHA256", hashlib.sha256)):
        lines.append(f"{title}:")
        for key in files:
            data = (work / key).read_bytes()
            lines.append(f" {digest(data).hexdigest()} {len(data):>10} {key.removeprefix(root)}")
    (work / f"{root}Release").write_text("\n".join(lines) + "\n")
    return files


class Signer:
    def __init__(self, home: Path) -> None:
        home.mkdir(mode=0o700, parents=True)
        self._env = os.environ | {"GNUPGHOME": str(home)}
        key = os.environ.get("APT_SIGNING_KEY")
        if not key:
            sys.exit("APT_SIGNING_KEY is not set")
        self._gpg("--import", input=key)

    def sign(self, release: Path) -> None:
        self._gpg("--clearsign", "--output", str(release.with_name("InRelease")), str(release))
        self._gpg("--detach-sign", "--armor", "--output", f"{release}.gpg", str(release))

    def _gpg(self, *args: str, input: str | None = None) -> None:
        subprocess.run(
            ["gpg", "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback", *args],
            input=input, env=self._env, text=True, check=True,
        )  # fmt: skip


# -- images --------------------------------------------------------------------------

_IMAGE = re.compile(r"^images/nocs-(.+)-pi5-arm64\.img\.xz$")


def publish_image(bucket: Bucket, keep: int, files: list[Path]) -> None:
    print("Uploading the image")
    images = [f for f in files if f.name.endswith(".img.xz")]
    if len(images) != 1:
        sys.exit("give exactly one .img.xz")
    # The image last, so that a listing never shows it without its checksum.
    for path in sorted(files, key=lambda f: f.name.endswith(".img.xz")):
        bucket.put(path, f"images/{path.name}")
    # Image names spell the version's "~" as "-" (packaging/image/build.sh); NOCS
    # versions have no Debian revision, so every "-" was a "~".
    versions = [m[1] for key in bucket.list("images/") if (m := _IMAGE.match(key))]
    versions.sort(
        key=functools.cmp_to_key(lambda a, b: compare(a.replace("-", "~"), b.replace("-", "~")))
    )
    for version in versions[:-keep]:
        for key in bucket.list(f"images/nocs-{version}-pi5-arm64."):
            bucket.delete(key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--local", type=Path, help="a directory instead of the bucket")
    commands = parser.add_subparsers(dest="command", required=True)
    debs = commands.add_parser("debs", help="add packages to suites")
    debs.add_argument("--suite", action="append", required=True, help="name:versions to keep")
    debs.add_argument("files", nargs="+", type=Path)
    image = commands.add_parser("image", help="upload an image with its checksum and manifest")
    image.add_argument("--keep", type=int, default=2)
    image.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()

    bucket = Bucket(args.local)
    if args.command == "debs":
        suites: dict[str, int] = {}
        for spec in args.suite:
            name, _, keep = spec.partition(":")
            suites[name] = int(keep or 5)
        publish_debs(bucket, suites, args.files)
    else:
        publish_image(bucket, args.keep, args.files)


if __name__ == "__main__":
    main()
