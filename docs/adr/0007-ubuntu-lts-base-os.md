# 0007. Ubuntu Server LTS as the base OS

Date: 2026-10-27 · Status: Accepted

## Context

Debian and Raspberry Pi OS package only the INDI core, with a delay, and not
the third-party drivers (e.g. `indi-asi` for ZWO, which embeds a proprietary
SDK, or `indi-gphoto`). The official INDI PPA publishes the full driver set
for Ubuntu LTS on arm64 and amd64. Ubuntu Server supports the Raspberry Pi 5.

## Decision

Ubuntu Server LTS is the supported base for both the Raspberry Pi image and
PC installs. Development on other distributions uses a container with the same
base.

## Consequences

- One package base and one behavior on every target.
- Some Raspberry Pi OS conveniences (raspi-config, tighter firmware tooling)
  are not available.
- NOCS depends on the INDI PPA release cadence for each Ubuntu LTS.
