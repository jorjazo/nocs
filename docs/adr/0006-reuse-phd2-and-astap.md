# 0006. Reuse PHD2 for guiding and ASTAP for plate solving

Date: 2026-10-27 · Status: Accepted

## Context

Guiding and plate solving are complex, well-solved problems. Re-implementing
them would consume a large part of the available development time.

## Decision

- **Guiding:** PHD2, run as a process managed by nocsd and controlled through
  its JSON-RPC event server (port 4400).
- **Plate solving:** ASTAP command-line, with hints from the mount position and
  the optical train's field of view; blind solve as fallback.

Autofocus, polar alignment, centering and the sequencer are implemented in
NOCS.

## Consequences

- Proven guiding and fast solving on the Pi from day one.
- PHD2 is a GUI app: headless operation requires a virtual display and
  automated profile management (spike needed).
- External processes must be supervised and restarted on failure.
