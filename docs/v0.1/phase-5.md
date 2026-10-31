# Phase 5 plan — Focus & sequence

Status: in progress (autofocus) · Last updated: 2026-10-31 · Roadmap: [Phase 5](../roadmap.md#phase-5--focus--sequence)

Goal: a full unattended night.

**Exit (field test):** start a multi-filter sequence at dusk and wake up to a
completed, parked session — including a meridian flip.

Autofocus comes first, while phases 3 and 4 settle the APIs the sequencer will
call (solve and centre, guiding and dithering). The sequencer, its triggers and
the session report are planned when those land; autofocus is built so that the
sequencer can run it inside its own job ([ADR 0021](../adr/0021-autofocus.md)).

## Stages: autofocus

| # | Stage | Contents | Check | Status |
|---|---|---|---|---|
| 5.1 | Curve and sweep | `nocs.focus.curve`: hyperbola fitted by weighted least squares on HFR², refined on the HFR, R²; `nocs.focus.sweep`: positions within the travel, extension on one side, moves that approach from one direction with an overshoot, the quality checks, a suggested step ([ADR 0021](../adr/0021-autofocus.md)) | Synthetic curves and one measured on the simulators | Implemented |
| 5.2 | Metrics and frames inside a job | Star metrics in the worker without previews and without dropping frames; a public way for workflows to take a frame inside their own job (shared with phase 3.2's solve job): `CaptureService.take` and `measure` | Simulators: the HFR follows the focuser | Implemented |
| 5.3 | Autofocus job | `AutofocusService.run` inside any job holding the camera, focuser and wheel; its own job from the API; first frame, sweep, extension, fit, final frame, back to the start on failure or cancel; `autofocus` state with the points as they come | Simulators (1000 mm): from focus and from far out of it; no stars; cancel restores | Implemented: `POST /api/autofocus`; on the simulators it found 36282 for a best focus of 36667 (step 4000, R² 0.98) |
| 5.4 | Settings and temperatures | Sweep settings per imaging train in the profile (`imaging.autofocus`, read as saved: no reconnection), backlash per physical focuser (`focusers.json`, ADR 0016 keys; `PUT /api/focuser/backlash`); focuser and ambient temperatures sampled into the catalog every minute (`GET /api/temperatures`); finished runs in the catalog (`GET /api/autofocus/runs`); `AMBTEMP`, `HUMIDITY` and `DEWPOINT` in FITS headers (drivers already write `FOCUSPOS` and `FOCUSTEM`) | Simulators (writable focuser temperature, weather simulator) | Implemented |
| 5.5 | Focus screen | Full-screen flow `#/focus`: settings with an advanced disclosure, live V-curve with the fit, best position / HFR / stars / temperature, result or the reason it failed; from Live view's focuser and the focuser sheet (Tonight's checklist when phase 3 builds it); en/es | Phone, wide, Night mode | Implemented: checked in the browser against the simulators (focused at 36693 for 36667; no stars; Night mode) |
| 5.6 | Lab check | EAF moves and overshoot, time per point with the 26 MP camera, temperatures from the EAF and the PPBA, a clean failure with the cap on; checklist for tuning under the sky | Lab Pi | |

## Measured

- The CCD simulator reads the focuser simulator's `FWHM`:
  `seeing + 0.5625·((x − best)/5000)²` arcseconds, best ≈ 36667 when the driver
  starts at 50000. Median HFR of 2 s frames at 1000 mm: 1.67 px at focus, 2.6 px
  10000 steps away, 5.4 px 20000 away. At 250 mm it stays under 2.1 px.
