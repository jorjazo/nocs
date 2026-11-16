# 0053. Tonight is the night and how the rig stands: its checklist connects, focuses and polar aligns

Date: 2026-11-16 · Status: Proposed · Amends: [ADR 0041](0041-preparation-steps-run-when-they-can.md) (the checklist's steps and their order)

## Context

The maintainer is redefining every view so that each has one purpose that says what
belongs in it ("Experiencia NOCS"). Tonight's is general information about the night
and the current state. Its checklist (ADR 0041) ran connect, polar align, focus,
frame the target, guide; framing and guiding belong to the views that will hold the
target and the sequence. Facts:

- **Polar alignment plate solves** (ADR 0034): it needs focused stars, so focusing
  comes first.
- **Connecting meant going to Rig**, though nearly always it is the profile used
  last (the selected one, `equipment.active`).
- **The state already holds** most of what the new cards show: the mount, the power
  box, the camera's cooler, the clock, the GPS, the box's health. Missing were the
  CPU's use, who is connected and what lies where the mount points.

## Decision

- **The checklist** has Connect, Focus (with a focuser) and Polar align (where it
  applies), in that order; the rule of ADR 0041 stays (the next step that can run
  carries the primary button; a blocked one says why and where to fix it). Connect
  offers "Connect <profile>" for the selected profile besides "Open Rig" (the owner
  only); Focus goes straight to the focuser's calibration while it has none. The
  server's `preparation` still reports `frame` and `guide` for the views that will
  use them.
- **Tonight's cards**, each opening and closing, with a summary and a warning chip
  that show while closed (the browser keeps which are open): the checklist first and
  open while a step is left, last and closed once all are done; then the night
  (open at first; how much of the dark window is left, and of it without the Moon),
  Pointing, Weather (ADR 0051), Actuators, Location and time, Host (closed at first).
- **Pointing**: the mount's altitude and azimuth and J2000 coordinates; what is there
  (tonight's target when it is within the main camera's frame, else the Sun or the
  Moon, else the nearest catalog object, from `GET /api/sky/pointing`); its altitude
  through the night; the guiding RMS. Parked and no mount say so.
- **Actuators**, read only: dew heaters (power, current, fixed or automatic), 12 V
  outputs, the input (a warning under 12.0 V, a problem under 11.5 V), the camera's
  cooler (the sensor against its target, its power, the ramp; a warning when it stays
  more than 1 °C off once the ramp had time, plus 5 minutes).
- **Location and time**, for the owner only (ADR 0047): the active site and its zone
  (ADR 0052), the box's time and what keeps it, the mount's site (against the active
  one) and whether NOCS gave it the time, the GPS; a warning with a link to the site
  when something is off.
- **Host**: CPU use (new in `system.health.cpu_used`), memory, room for frames and on
  the system disk, the box's sensors, and who is connected (new `clients`: the owner
  sees each paired device; observers only how many observers watch).

## Consequences

- Framing and guiding are reachable only from their own screens until the target and
  sequence views take them.
- The mount's clock is shown as last read, which may be old: it is not compared with
  the box's.
- The cooler's grace period starts when a browser first sees the target: reloading
  the page restarts it.
