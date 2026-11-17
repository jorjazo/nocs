# 0050. CI pulls the simulators' and PHD2's images from GHCR

Date: 2026-11-17 · Status: Proposed

## Context

CI's integration tests run against two images from `dev/compose.yaml`: `indi` (the INDI
simulators and the ~300 MB GSC catalog, from `ppa:mutlaqja/ppa`) and `phd2` (headless
PHD2, from `ppa:pch/phd2`). Every run built them with bake from the Actions cache,
rebuilt each ISO week (`APT_REFRESH`) to follow the PPAs.

The cache held only while every layer matched. On 2026-11-17 `ubuntu:26.04` resolved to
a new digest between `main`'s run (`sha256:065aa86…`) and a pull request's
(`sha256:d66b366…`). That invalidated every layer, so every pull request downloaded
everything from Launchpad again. Launchpad answered 503 or "Connection failed", each time
on a different package (`libindi-data`, `gsc`, `gsc-data`). The `integration` job of
jorjazo/nocs#58 failed four times in a row, and no test ever ran.

There is no fallback archive. Ubuntu 26.04's own archive has `indi-bin` 1.9.9, while the
PPA has 2.2.5, and it has no `gsc` or `phd2`.

## Decision

- A workflow, `.github/workflows/dev-images.yml`, builds both images with bake from
  `dev/compose.yaml`. It publishes them on GHCR as `ghcr.io/jorjazo/nocs-dev-indi` and
  `ghcr.io/jorjazo/nocs-dev-phd2`, tagged `latest` and with the ISO week (`2026-W47`). The
  packages are public.
- It runs:
  - on pushes to `main` that change `dev/indi`, `dev/phd2`, `dev/compose.yaml` or the
    workflow itself, building with the Actions cache;
  - every Monday, without the cache and pulling `ubuntu:26.04` again, to follow the
    PPAs and the base image. This replaces `APT_REFRESH`;
  - by hand, also without the cache.
- CI's `integration` job pulls those images. It builds an image itself, from the PPAs
  and the cache the publishing workflow writes, only when the pull request or push
  changes that image's directory, or when the pull fails after three attempts.
- The Containerfiles make apt retry each download (`Acquire::Retries "5"`).
- `dev/compose.yaml` (and the soak's) names the images by their GHCR names.
  `docker compose -f dev/compose.yaml up -d --build` still builds them locally;
  `docker compose -f dev/compose.yaml pull` takes CI's images instead.

## Consequences

- A pull request that leaves `dev/indi` and `dev/phd2` alone never contacts Launchpad.
  Pulling ~a few hundred MB from GHCR also takes less time than building from the cache.
- A pull request that changes an image still depends on Launchpad, as before, with
  apt's retries. So does `main`'s weekly build, but a failure there only leaves last
  week's images in place.
- A new INDI or PHD2 from the PPAs reaches CI when Monday's build publishes it, not when
  each run builds it. A release that breaks the tests breaks every run from then on,
  which is no worse than before. To avoid it, the weekly build could publish only its
  week's tag and move `latest` once CI passes against it.
- The images on GHCR are a few hundred MB each, and a new week tag is added each week.
  Public packages cost nothing, but old week tags may need pruning eventually.
- A manual run from a branch other than `main` also moves `latest`. It is a way to try an
  image change before merging it, so use it knowingly.
