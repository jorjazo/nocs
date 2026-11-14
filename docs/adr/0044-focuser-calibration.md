# 0044. Focuser calibration: backlash each way, an overshoot that returns, and the scale

Date: 2026-11-14 · Status: Proposed · Amends: [ADR 0021](0021-autofocus.md) (where the overshoot comes from)

## Context

Autofocus takes up backlash by reaching every position from one direction and
overshooting a target before moves the other way (ADR 0021); the overshoot was a
guess, learnt by failing under the sky. On rc5's night with the GT81
([field notes](../roadmap/v0.1/rc5-field-notes.md)) the EAF's backlash was 1000 steps
or more and not constant, and runs that succeeded left the focus ~190 steps out
(ADR 0043). The maintainer asked for a calibration that finds the backlash (each
way?) and the smallest step that still means something to focus. Facts:

- **No feedback but the stars.** The EAF reports motor steps, not where the drawtube
  is. Only frames tell where the optics are.
- **An arm of the V is a ruler.** Away from focus the HFR grows almost linearly with
  the defocus and the seeing matters less: on the GT81, 0.042 px per step on both arms,
  from 1.5 px at focus to 8 px at ±190 steps with ~30 stars left. Near focus the
  curve is flat and says little about small moves.
- **One frame measures a move.** On an arm, a frame's HFR gives the optics' position
  to a few steps (a step's change is ~0.04 px against a seeing noise of ~0.1 px), so
  the motion lost at a reversal is the commanded move minus the one measured: no
  need to walk the dead band point by point.
- **A pure dead band has one width**, the same at both reversals; gravity on the
  camera, friction and a loose coupling make real focusers stray from it. The night's
  data fits no single width. Approaching from one direction needs, for its final leg
  and for the leg before it, an overshoot at least as large as the motion lost at
  either reversal.
- **What failed is the round trip**: leave a position and come back to it with the
  approach pattern. That is what a calibration must check, not only a width.
- **The scale.** A star defocused by Δ is a disk of diameter Δ/N, whose HFR is 0.354
  times it; the V's asymptote `a/b` (px per step) with the focal ratio and the pixel
  size gives µm per step (~2.1 on the GT81). The critical focus zone, 4.88 λ N² with
  λ = 0.55 µm, is then a number of steps (~28 at f/4.74).
- **Drivers can compensate themselves**: INDI's `FOCUS_BACKLASH_TOGGLE` and
  `FOCUS_BACKLASH_STEPS` (the EAF and the focuser simulator have them). With them on,
  what NOCS measures is what is left after the driver's compensation, and it changes
  if someone changes that setting.
- **Where it lives.** Backlash and µm per step belong to the focuser's mechanics: the
  EAF and the drawtube it turns. NOCS keeps such settings per physical focuser
  (ADR 0016, `focusers.json`); a focuser moved to another scope keeps a calibration
  that no longer applies.
- The simulators have no backlash (ADR 0021); a test focuser with a dead band is
  needed for everything but the plain path.

## Decision

- **A calibration job** locks what autofocus locks (main camera, focuser, filter
  wheel) and never moves the mount. From the Focus screen, the focuser's sheet
  (Rig), a failed autofocus (*backlash*, *missed*), and Tonight's checklist while the
  focuser has no calibration for the active profile.
- **Refuse driver compensation.** With `FOCUS_BACKLASH_TOGGLE` on, the job fails
  before moving and the screen offers to turn it off (`PUT /api/focuser/driver-backlash`);
  NOCS alone takes up backlash.
- **Steps of the job:**
  1. *Autofocus* with the train's sweep and a large overshoot (the larger of 2000
     and three times the saved one): its curve gives the best focus `c`, its HFR
     `a` and its width `b`. A failed autofocus fails the calibration with its reason.
  2. *Ruler*: six frames on the arm on the approach side, from 1.2 `b` to 5 `b` past
     the best focus, each reached moving that way; position as a quadratic in HFR,
     least squares; its residuals give the noise in steps (σ).
  3. *Reversals*, twice each way: from the arm's far end, move back in chunks of at
     most 2.5 `b` (so the optics cannot reach focus and the other arm) until a frame
     shows the optics moved by more than max(4 σ, 0.25 `b`); the motion lost is the
     commanded total minus the motion measured. One more chunk checks that the optics
     now follow the motor (less than 60 % of it: *slip*, a warning). Then the same
     towards the far end. After the first reversal each way, the next one starts with
     a jump of the backlash found less 2.5 `b`. More than 6000 steps without motion
     (beyond one chunk) fails (*no movement*); leaving the focuser's travel fails (*travel*).
  4. *Round trips*: the overshoot is 1.3 times the largest motion lost, rounded up
     (at least one sweep step). Three times: from the arm's far end, approach a
     position on the arm as autofocus does and check that the frame there puts the
     optics within max(4 σ, 0.3 `b`) of it. A miss raises the overshoot by half and
     starts the trips again, at most three times; then the calibration fails (*not
     repeatable*).
  5. *Back to focus*: approach the best focus with that overshoot.
- **Results**: the motion lost each way (inward, outward: every measurement), the
  overshoot that passed the round trips, the noise, µm per step and the critical
  focus zone in steps (when the profile has the aperture and the camera its pixel
  size), the smallest significant step (3 σ, rounded up) and the sweep step that
  autofocus's fit suggests. The state shows them as they come under
  `focus_calibration`; a finished calibration is saved with the focuser's settings
  (with the profile it was measured with and when), and **its overshoot becomes the
  focuser's**. The sweep step is offered, as autofocus offers it, for the imaging train.
- A failed or cancelled calibration goes back to the best focus when autofocus found
  one, otherwise to where it started, with the large overshoot.
- **Per physical focuser**, as ADR 0021 keeps the overshoot; the record names the
  profile, and Tonight's checklist asks for a calibration when it was another one.

## Consequences

- A calibration takes a few minutes and a clear patch of sky near focus; it answers
  "how much backlash" with every measurement each way, so a focuser whose backlash
  varies shows it, and the overshoot it leaves is one that came back three times.
- The approach direction stays the user's choice: with an overshoot at least as large
  as the motion lost either way, either direction returns.
- The thresholds (4 σ, 0.25 `b`, 60 %, 1.3 ×, 6000 steps) are first guesses for the
  GT81's night; the simulators only check the plain path (no backlash).
- A focuser calibrated with one profile and used with another is asked to calibrate
  again, even when only the camera changed; that costs minutes, not a night.
