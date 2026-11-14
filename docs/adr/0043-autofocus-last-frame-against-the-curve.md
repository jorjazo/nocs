# 0043. Autofocus checks its last frame against the curve, and approaches again

Date: 2026-11-14 · Status: Proposed · Amends: [ADR 0021](0021-autofocus.md) (quality check 6, going back to the start)

## Context

On rc5's night with the GT81 and its 0.8× reducer (2026-11-12,
[field notes](../roadmap/v0.1/rc5-field-notes.md)) four autofocus runs succeeded with
clean V-curves (R² 0.97–0.99, best HFR 1.4–1.6 px) and left the focuser about 190
steps out of focus every time: their last frames measured 7.4–8.4 px. ADR 0021's
check 6 compares the last frame with the first one, and each run began where the
previous one had left the focuser, already out of focus, so it passed. Facts:

- The ZWO EAF on that focuser has a backlash of 1000 steps or more (about 2 mm of
  drawtube at ~2.1 µm per step), not always the same: one run showed no movement of
  the optics over −1440 and +1440 steps. The saved overshoot was 830.
- A failed run goes back to the start with the same overshoot, and misses it the same
  way: after a failure from a focused start, the next run found 5 stars.
- The fitted hyperbola's `a` is the HFR at its best focus; a frame there with seeing
  as during the sweep measures close to it (1.4–1.6 px against `a` 1.43–1.55).
  1.5 × `a` lies about 1.1 `b` from the best focus (40 steps, 1.4 critical focus
  zones, on the GT81).
- Taking up backlash with a larger overshoot costs only time: the EAF covers ~230
  steps a second.

## Decision

- **Against the curve.** The last frame at the fitted best focus must have enough
  stars and an HFR no larger than 1.5 × `a` (`off_focus`). Check 6 (against the first
  frame, 10 %) stays, after this one.
- **Approach again.** A last frame that fails it makes the run approach the best focus
  once more, past it by twice the overshoot (twice the step without one), and measure
  again. If that frame passes, the run succeeds and offers that overshoot to keep for
  the focuser (`suggested_overshoot` on a run that succeeded); if not, the run fails
  as *missed* (the focuser's backlash larger still, or the sky changed).
- **Going back.** A failed or cancelled run goes back to its start with twice the
  overshoot.

## Consequences

- A focus missed by backlash costs one more move and frame (~10 s on the EAF) instead
  of a night out of focus; a missed one that a second approach does not fix fails
  loudly.
- Seeing that worsens between the sweep and the last frame by more than half fails a
  run that ADR 0021 would have passed; 1.5 is a first guess to tune on real nights.
- A failure as *missed* cannot tell backlash from the sky; the focuser calibration
  (measuring the backlash and the overshoot that reaches a position again) is what
  should make it rare.
