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
| 5.6 | Lab check | EAF moves and overshoot, time per point with the 26 MP camera, temperatures from the EAF and the PPBA, a clean failure with the cap on; checklist for tuning under the sky | Lab Pi | Done indoors (below); found and fixed: moving back after a cancel in mid-move, and a flat curve from hot pixels. Tuning waits for a clear night |

## Measured

- The CCD simulator reads the focuser simulator's `FWHM`:
  `seeing + 0.5625·((x − best)/5000)²` arcseconds, best ≈ 36667 when the driver
  starts at 50000. Median HFR of 2 s frames at 1000 mm: 1.67 px at focus, 2.6 px
  10000 steps away, 5.4 px 20000 away. At 250 mm it stays under 2.1 px.

## Lab check (2026-10-31, lab Pi 5, indoors with the cap on)

ZWO EAF (serial `0F21209019472401`, firmware 3.2.2) on the 380 mm f/4.7 scope,
ASI2600MC Duo, PPBA as the weather role; a test nocsd beside the maintainer's,
without the driver FIFO.

- **Moves.** The EAF covers 300 steps in 1.3 s, 1500 in 4.8 s (~230 steps/s plus
  ~0.2 s per move). With synthetic stars (a hyperbola at the start + 600 steps)
  a 9-point sweep with step 300 took 23 s, every point reached moving outward
  (overshoots of one step before the first point and before the best focus), and
  it ended exactly on the best focus (6831 for 6831).
- **Cancelling mid-move.** The EAF goes on to the target of the move in progress
  and refuses another one until it gets there ("Failed to set position. Error: 5"),
  so moving back failed and the focuser stayed 300 steps off. Moving back now
  aborts, waits for the focuser to hold still, and tries a refused move once more:
  checked again on the EAF (cancelled at 5931 while moving; it stopped at 5940 and
  went back).
- **With the cap on** the camera's hot pixels pass as ~20 "stars" of 0.82–0.84 px
  HFR in every frame: the first check (10 stars) passes and the sweep runs. It
  ended as a bad fit after extending to 12 points (80 s); a new check for a flat
  sweep (largest HFR under 1.2 × the smallest) now stops it after the first 9
  points (52 s) with its own reason.
- **Time per point** with 2 s exposures of the 26 MP frame and a step of 300: about
  5–6 s (move, exposure, download; the stars of the previous frame are measured
  meanwhile).
- **Temperatures.** Focuser 26.7 °C and ambient 27.8 °C, 45 % humidity, dew point
  14.8 °C (PPBA) sampled into the catalog each minute; a saved frame carried
  `AMBTEMP`, `HUMIDITY`, `DEWPOINT` from NOCS and `FOCUSPOS`, `FOCUSTEM` from the
  driver. The EAF's own temperature compensation (`TEMPC_SWITCH`) is off and must
  stay off while NOCS focuses.

## Tuning under the sky (first clear night)

1. Focus by hand in Live view until stars show; note the position.
2. Run autofocus with a step of 100–300 on the 380 mm scope (9 points, 2–3 s):
   the ends of the sweep should be clearly out of focus (about 2.5 times the best
   HFR). Take the step the result suggests and run again; save it (Remember).
3. Repeat three times without touching anything: the best positions should agree
   within a fraction of a step; note the spread.
4. Approach direction and overshoot: run once outward and once inward (Advanced);
   the difference between their best positions is the backlash to cover.
5. Note R² and the last frame's HFR against the first of each run, to set the
   thresholds (contrast 1.2, R² 0.8, worse 10 %) from real curves.
6. Through a passing cloud or with the cap on: the run must fail with its reason
   and go back to where it started.
7. Two filters (L and Ha) for the offsets the sequencer will need later.
