# 0035. Apt repository, signing and release publishing

Date: 2026-10-31 · Status: Proposed

## Context

ADR 0025 decided on one signed apt repository with `stable` and `testing` suites,
and ADR 0026 on one Raspberry Pi image with the D50 star database, but both left
the host open. Facts that shape the choice:

- The `nocs` package is about 120 MB per architecture, more than the 100 MB per
  file that GitHub Pages (a git repository) accepts.
- The image is 3.3 GB compressed, more than the 2 GiB per file of GitHub Releases.
  D50 (874 MB) barely compresses, and an image without it does not solve dense
  Milky Way fields (ADR 0018).
- One maintainer, 5–10 h a week: the host must need no server to keep up, and
  cost nothing or close to it.
- Options considered: Cloudflare R2 (S3 compatible object storage, 10 GB free,
  no charge for downloads; its `r2.dev` address is rate limited and meant for
  development, so production needs a custom domain); Cloudsmith's open source plan
  (free and managed, but its published quotas disagree, 10–50 GB stored and
  100–200 GB delivered a month, about 30–60 image downloads); GitHub Releases as a
  flat apt repository (free, but the image still needs another host); a VPS
  (a server to maintain).

## Decision

### Host

- **Cloudflare R2**, served from a **domain of the maintainer's** (the repository
  variable `NOCS_APT_URL`, for example `https://apt.example.org`), holds the apt
  repository and the images. One bucket:

  ```
  nocs-archive-keyring.asc                     the public key
  dists/{stable,testing}/InRelease, Release, Release.gpg
  dists/{stable,testing}/main/binary-{amd64,arm64}/Packages(.gz)
  pool/main/n/nocs/nocs_<version>_<arch>.deb
  images/nocs-<version>-pi5-arm64.img.xz       with .sha256 and .manifest.txt
  ```

- CI writes to it with the AWS command line (S3 API) and an R2 token kept in the
  repository's secrets (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`,
  `R2_BUCKET`). Without them, publishing is skipped and packages stay CI artifacts.
- **GitHub Releases** carries, for each tag, the release notes, both `.deb` files,
  the image's checksum and manifest, and a link to the image on R2.

### Signing

- **The signing key lives only in CI** (the secret `APT_SIGNING_KEY`, an Ed25519
  OpenPGP key without a passphrase). `packaging/repo/new-key.sh` makes it, stores it
  as the secret and writes its public half to `packaging/repo/nocs-archive-keyring.asc`;
  no copy is kept anywhere else.
- The `nocs` package ships the public key in
  `/usr/share/keyrings/nocs-archive-keyring.asc`; the image's deb822 source and the
  PC instructions name it with `Signed-By`. Shipping it in the package is how the
  key is rotated: a release ships the old and the new key, signed with the old one,
  and the next release is signed with the new one. A leaked key is rotated the
  same way, and anyone who installed from it is told in the release notes.

### Suites

- **`testing`**: every push to `main` whose packages build and pass their install
  test (the other CI jobs run alongside, so a broken build can reach `testing` until
  the next push fixes it). The last **5** builds per architecture are kept.
- **`stable`**: tagged releases (`v*`), also added to `testing` so that it never
  sorts behind `stable`. The last **3** releases are kept.
- Each suite's `Packages` files are its state: a publish downloads them, not the
  packages, adds the new entries, keeps the newest versions, writes `Release`,
  signs it, uploads the new packages first and the indices last, and only then
  deletes packages that no suite names any more (`packaging/repo/publish.py`).
  Publishes run one at a time.
- A flashed Pi follows `stable`. Switching to `testing` is a documented edit of
  `/etc/apt/sources.list.d/nocs.sources`; there is no switch in the app in v0.1.

### Images

- Built for each tag (and on demand), named `nocs-<version>-pi5-arm64.img.xz`;
  a tag's image is uploaded to `images/` and its source names `stable`, an image
  built on demand stays a CI artifact and names `testing`. The last **2** release
  images are kept.

## Consequences

- Storage stays around 9 GB (5 × 2 testing builds, 3 × 2 releases, 2 images),
  inside R2's free 10 GB; anything above costs cents a month. Downloads cost
  nothing, however popular the image gets.
- The domain is the one paid piece (around US$10 a year), and moving the
  repository means changing the source on every installed box: the domain must
  outlive the host.
- A key kept only in CI is as safe as the repository's secrets: anyone who can
  change the workflows can sign. That is the same trust as merging to `main`.
- `testing` users get what `main` builds within minutes; a regression there is
  fixed forward, with apt's cached previous package as the way back (ADR 0025).
