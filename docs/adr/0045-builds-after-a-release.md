# 0045. Builds after a release sort after it

Date: 2026-11-14 · Status: Proposed · Amends: [ADR 0025](0025-packaging-and-updates.md) (versions between releases)

## Context

ADR 0025 named the builds between releases `X.Y.Z~git<commits>.g<commit>`, sorting
before `X.Y.Z`. That holds while `server/pyproject.toml` already names the next
version. It does not after a tag: `packaging/release.sh` bumps the version in a pull
request and then tags `main` at that version, so from the tag until the next bump
`main` builds `0.1.0~rc5~git219.g…`, which sorts *before* the `0.1.0~rc5` it follows.

That bit the lab Pi on 2026-11-14. It follows `testing`, which carries the releases
too (ADR 0035), and had a build from after rc5 installed. Its update installed
`0.1.0~rc5`, which apt thinks is newer, instead of `main`'s newest build: an older
NOCS presented as an upgrade, and one that broke the box because it ran as another
user than the build it replaced. Until the next bump, every update on `testing` would
have gone back to the release.

## Decision

- A tagged release is still just its package version (`0.1.0~rc5`, `0.1.0`).
- A build whose pyproject version is **not tagged yet** stays
  `<version>~git<commits>.g<commit>`: it sorts before that release.
- A build whose pyproject version's tag (`v<pep440>`) **is an ancestor** of it becomes
  `<version>.git<commits>.g<commit>`: it sorts after that release and before the
  next version's builds.
- `.` rather than `+` (the usual mark for "after"): `+` in a file name is read as a
  space by some S3-compatible hosts, the apt repository is on one (ADR 0035), and
  image names keep a version's `.` as it is.

One cycle, in apt's order: `0.1.0~rc5`, `0.1.0~rc5.git220.g…`, (bump) `0.1.0~rc6~git231.g…`,
`0.1.0~rc6`, `0.1.0~rc6.git233.g…`, `0.1.0`, `0.1.0.git240.g…`, (bump) `0.1.1~git241.g…`.

## Consequences

- A box on `testing` always moves on to `main`'s newest build, release or not; one on
  `stable` gets only releases. To stay on one build on `testing`, hold it
  (`apt-mark hold nocs nocs-appliance`); a rollback from the app is undone by the next
  update there.
- The version can be bumped whenever it suits: right before tagging, as
  `release.sh` asks, or earlier.
- Builds from a branch that does not contain the tag keep `~git`. Two branches can
  still build the same `<commits>` count with different commits; only `main` publishes
  to `testing`, so the repository never holds both.
