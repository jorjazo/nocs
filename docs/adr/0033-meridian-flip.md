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
- On the lab AM5 (2026-11-01, indoors, `indi_lx200am5` 1.4, Dec −20°): its own flip
  was off as the maintainer had left it (`MERIDIAN_FLIP` `INDI_DISABLED`), with
  `POST_MERIDIAN_TRACK` `TRACK` and `MERIDIAN_LIMIT` 15 (the driver's maximum). It
  reported the pier side after every go to and while tracking, like the simulator:
  a go to 18 min east of the meridian put it on `PIER_WEST`, 18 min and 1 h west of
  it on `PIER_EAST` (a go to across the meridian takes 30 s instead of 4–17 s), and
  back east on `PIER_WEST` again. Tracking across the meridian it kept its side and
  kept tracking (5 min past it, then the flip). A NOCS sequence (30 s frames, flip
  2 min past the meridian, no guiding or centring) started 4 min east of the
  meridian took 10 frames, flipped at +1.5 min (the next frame would have ended past
  +2 min), in 33 s, `PIER_WEST` → `PIER_EAST`, then took its other 6 frames: none
  cut. At home (Dec −90°) the reported side follows the last pointing, so it means
  nothing there.

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
  (2026-11-01, soak test: on the simulators PHD2 turned its calibration's RA for the
  reported side but Dec guiding then ran away, 0.2 to 23 px in 20 s, and no dither
  settled until the guiding policy ended the night. Whether Dec must be reversed
  after a flip depends on the mount, so guiding now calibrates again after every
  flip, a few minutes once a night, instead of `flip_calibration`.)
- **The guard.** While a run exists, paused included, a task looks every 30 s: a
  target pointed east and now 15 minutes past its flip point with no flip under way
  makes NOCS stop tracking, once per pointing, with an event. Resuming flips first.
- **The mount's own flip** (AM5/AM7 `MERIDIAN_FLIP`) is left as the user set it. With
  it off and `POST_MERIDIAN_TRACK` on `TRACK` (the lab AM5's settings) the mount
  tracks on past the meridian until NOCS flips it, which is what a sequence needs;
  with it on, its limit must lie past NOCS's flip point (the field checklist says
  so). The AM5's automatic flip itself was not tried.

## Consequences

- A night across the meridian needs no user: the frame in progress is never cut, at
  most a few minutes wait for the meridian.
- The flip needs the site (hour angles): a sequence with a flip trigger asks for it,
  like one that waits for dusk.
- NOCS does not turn the mount's automatic flip off during a sequence; the field
  checklist asks to keep it off on the AM5/AM7 (or its limit past NOCS's flip
  point). The AM5 reports its pier side, so the flip's check works there.
