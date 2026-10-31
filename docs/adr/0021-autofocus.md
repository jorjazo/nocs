# 0021. Autofocus: V-curve sweep with a hyperbolic fit

Date: 2026-10-31 · Status: Proposed

## Context

Phase 5 brings autofocus: from the Focus screen by hand, and later as an
instruction and a trigger of the sequencer (on a temperature change, a filter
change, HFR growth, elapsed time). Facts that shape it:

- **The curve.** Near focus, seeing sets the star size; far from it, the
  out-of-focus disk grows linearly with the distance. HFR against focuser
  position is a V with a rounded tip, which a hyperbola describes:
  `hfr(x) = a·√(1 + ((x − c)/b)²)`, best focus at `c`. Its square is a parabola
  in `x`, so it can be fitted by linear least squares. NumPy is a dependency,
  SciPy is not.
- **Star metrics** come from the imaging worker (`sep`, median HFR in unbinned
  pixels, ADR 0012), which today drops a frame superseded by a newer one and
  always writes a preview.
- **The simulators** are usable: the CCD simulator reads the focuser simulator's
  `FWHM`, which is `seeing + 0.5625·((x − best)/5000)²` arcseconds. At the dev
  profile's 250 mm the HFR stays sub-pixel (0.5 px at focus, 2 px 27000 steps
  away); at 1000 mm it goes from 1.7 px to 5.4 px 20000 steps away, with ~50
  stars around Orion. This curve is a parabola in FWHM, not a hyperbola. The
  focuser simulator's temperature is writable; it has no mechanical backlash.
- **Backlash.** Gears and belts lose some steps when a focuser reverses. The
  ZWO EAF driver can compensate itself (`FOCUS_BACKLASH_*`), not every driver
  can, and the amount differs per focuser.
- **Steps mean different things** on every focuser and scope: how many steps
  span the critical focus zone depends on the focuser's mechanics and the
  scope's focal ratio, neither of which NOCS knows.
- **Jobs do not nest** (`nocs.jobs`): the sequencer will hold the camera,
  focuser and wheel locks for the whole sequence and must run autofocus inside
  its own job.

## Decision

- **Sweep.** Frames at `points` positions `step` apart, centred on the current
  position (shifted to stay within the focuser's travel), one frame per point
  by default. Defaults: 9 points, 1 frame per point, 2 s, binning 1, the
  camera's current gain; the step has no universal default (below).
- **Backlash by approach direction.** Every position is reached moving the same
  way (outward by default): the sweep runs in that direction, and any move
  against it (to the first point, to the best focus, back to the start) goes
  past its target by an overshoot and returns. The default overshoot is one
  step of the sweep. The driver's own compensation, where it exists, is left
  as the driver has it; NOCS does not combine both.
- **Fit.** A hyperbola, first by least squares on HFR² weighted by 1/HFR², then
  refined by a few damped Gauss-Newton (Levenberg-Marquardt) steps on the HFR
  itself. No parabolic or trend-line alternatives until real nights show a
  need.
- **Quality checks**, each with its own reason for the user:
  1. *no stars*: the frame at the starting position has fewer than 10 stars
     (clouds, the cap): fail before moving;
  2. *too few stars*: points under 10 stars or without an HFR do not count;
     fewer than 5 that count fail the run;
  3. *the curve never turns*: fewer than 2 points on one side of the lowest
     one add points on that side (up to 4, within the travel); still not
     turned, fail;
  4. *bad fit*: a curve that does not open upwards, a best focus outside the
     points, or R² under 0.8, fail;
  5. *worse*: a last frame at the best focus with an HFR more than 10 % above
     the starting one fails the run.

  A failed or cancelled run moves the focuser back to where it started.
- **Step.** Each successful run suggests a step that would put the ends of the
  sweep at 2.5 times the best HFR (from `b`); the Focus screen offers it. Until a
  first run, the user gives a step.
- **Where settings live.** What depends on the optics (step, points, exposure,
  binning) belongs to the profile's imaging train; what depends on the
  mechanics (backlash overshoot and approach direction) belongs to the physical
  focuser, keyed as in ADR 0016.
- **Reuse.** Autofocus is a function that runs inside a job holding the main
  camera, the focuser and the filter wheel; the API starts it in a job of its
  own that takes those locks. The mount is not locked. Its points arrive in the
  state as they are measured, under `autofocus`; finished runs, with the
  focuser's and the ambient temperatures, are kept in the catalog for the
  session report and the temperature trigger.
- **Metrics without previews.** The worker gets a measurement that never drops
  a frame and writes no preview.

## Consequences

- No new dependency; the fit is deterministic, needs no starting guess and is
  tested on synthetic curves and on curves measured on the simulators.
- Tests of the whole run need a profile with a longer focal length than the dev
  one (1000 mm), and find the simulator's best focus from its `FWHM` property,
  not from a constant.
- Only the approach-direction method is tested on the simulators, which have no
  backlash; the overshoot needed by real focusers is learnt in the lab and the
  field.
- Filter focus offsets, the temperature compensation of the position and the
  sequencer's triggers build on the stored runs later, without changing this.
- The thresholds (10 stars, R² 0.8, 10 %, 2.5×) are first guesses to tune under
  a real sky.
