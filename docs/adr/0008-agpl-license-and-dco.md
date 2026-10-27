# 0008. AGPL-3.0 license and DCO

Date: 2026-10-27 · Status: Accepted

## Context

NOCS is an open, hobby project whose purpose is to avoid lock-in. The
maintainer wants to prevent closed forks, including closed services built on
NOCS (remote access is a long-term goal).

- Permissive licenses (MIT, Apache-2.0) allow closed forks.
- GPL-3.0 requires source for distributed modifications, but not for software
  offered over a network.
- AGPL-3.0 additionally requires source for modified versions offered to users
  over a network.

## Decision

License NOCS under **AGPL-3.0-or-later** (the "or later" clause lets the
project adopt future AGPL versions without contacting every contributor).
Accept contributions under the Developer Certificate of Origin (`Signed-off-by`),
not a CLA.

## Consequences

- Modified versions, whether shipped in hardware or offered as a service,
  must remain open.
- Without a CLA, no single party (including the maintainer) can relicense the
  project as closed.
- External engines (INDI, PHD2, ASTAP) are separate processes; no license
  conflict.
- Some companies avoid AGPL code; acceptable for this project.
