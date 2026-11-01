# 0033. Sequences: the meridian flip

Date: 2026-11-01 · Status: Proposed

## Context

A German equatorial mount tracking a target from the east of the meridian must
change sides of the pier once the target crosses it; otherwise the telescope or the
camera runs into the pier. The phase 5 plan decided that NOCS flips, not the mount
(decision 2, ADR 0031), and that the flip comes with guiding, centring and a guard.
A spike on the simulators (2026-11-01, INDI's Telescope Simulator with
`SIM_PIER_SIDE` on and `FLIP_HA` 0):

- After a go to, the simulator reports `TELESCOPE_PIER_SIDE` from the target's hour
  angle: a target east of the meridian puts it on `PIER_WEST`, one west of it on
  `PIER_EAST` (INDI's convention: the side the telescope is on).
- Tracking across the meridian does not change sides by itself: four minutes past
  it the simulator still said `PIER_WEST`.
- A go to the same target once past the meridian changes sides (`PIER_EAST`): that
  is the flip.
- Still to measure on the lab AM5 (lab lock, with the maintainer's OK): whether its
  driver reports the pier side reliably (ADR 0015 says not always), what its own
  automatic flip (`MERIDIAN_FLIP`, `MERIDIAN_LIMIT`) does mid-exposure, and whether a
  go to past the meridian flips it.

## Decision

- **A flip trigger** (`FlipTrigger`, `after` minutes past the meridian, default 5)
  on the container that images the target. Templates add it unless turned off, with
  the target centred again after the flip when the template centres.
- **When.** The runner remembers the target's hour angle when the mount last went to
  it (a slew, a centring, a flip; in the checkpoint). Only a target pointed east of
  the meridian flips. Before each frame, with the frame's length (exposure plus a
  few seconds): a frame that ends before the flip point is taken; otherwise, once the
  target is past the meridian, the flip comes first (early rather than late), and
  before the meridian the run waits for it through safe points (pauses and stops
  work; one event says how long). A flip goes before any other trigger.
- **The flip** (`Flip` action): stop guiding, go to the target again (or centre it),
  check that the reported pier side changed (a mount that reports none is trusted),
  and, when the mount reports no side while the sequence guides, tell PHD2 to flip
  its calibration (`flip_calibration`); with a side reported PHD2 flips it itself.
  Guiding starts again before the next frame, as after any slew. A flip that fails
  is a `flip` failure: one retry 10 s later, then the session ends (park).
- **The guard.** While a run exists, paused included, a task looks every 30 s: a
  target pointed east and now 15 minutes past its flip point with no flip under way
  makes NOCS stop tracking, once per pointing, with an event. Resuming flips first.
- **The mount's own flip** (AM5/AM7 `MERIDIAN_FLIP`) is left as the user set it until
  the lab spike says what it does during a sequence; the rule stays that NOCS flips
  at a point inside the mount's limit.

## Consequences

- A night across the meridian needs no user: the frame in progress is never cut, at
  most a few minutes wait for the meridian.
- The flip needs the site (hour angles): a sequence with a flip trigger asks for it,
  like one that waits for dusk.
- Turning the mount's automatic flip off during a sequence, and the AM5's pier side,
  wait for the lab spike; until then the field checklist asks to set the AM5's limit
  past NOCS's flip point.
